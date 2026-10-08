"""AI Test Assistant: conversational test creation, execution and failure analysis."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.failure_analysis import CATEGORIES
from ..agents.nl_agent import plan_instruction
from ..db import get_db
from ..deps import Principal, get_principal, load_project, project_reader, project_writer, require_user
from ..models import (
    AssistantConversation,
    AssistantMessage,
    DiscoveredPage,
    Environment,
    Project,
    TestCase,
    TestExecution,
    TestResult,
)
from ..services import audit
from ..services.environments import default_environment, variable_names
from ..services.testcases import create_test_case, latest_discovery, preview_validation
from .projects import set_env_variable
from .runs import RunIn, create_execution
from .serializers import conversation_out, execution_out, message_out, test_case_out

router = APIRouter(tags=["assistant"])

CRED_RE = re.compile(r"\b(username|user name|login|email|password|api[ _-]?token|api[ _-]?key)\s*(?:is|=|:)\s*[\"']?([^\s\"',;]+)[\"']?", re.I)
SECRET_KEYS = {"password", "api_token", "api_key"}


class ConversationIn(BaseModel):
    title: str = Field(default="New conversation", max_length=200)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SavePlanIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    steps: Optional[list[dict[str, Any]]] = None


class RunPlanIn(BaseModel):
    test_case_id: uuid.UUID
    browser: str = "chromium"


def _conv(db: Session, principal: Principal, cid: uuid.UUID, minimum: str = "viewer") -> tuple[AssistantConversation, Project]:
    conv = db.get(AssistantConversation, cid)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    project = load_project(db, principal, conv.project_id, minimum)
    if principal.user is None or conv.user_id != principal.user.id:
        raise HTTPException(404, "Conversation not found")
    return conv, project


@router.get("/projects/{project_id}/assistant/conversations")
def list_conversations(project: Project = Depends(project_reader), principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AssistantConversation).where(AssistantConversation.project_id == project.id,
                                                         AssistantConversation.user_id == principal.user.id)
                      .order_by(AssistantConversation.created_at.desc()).limit(50))
    return [conversation_out(c) for c in rows]


@router.post("/projects/{project_id}/assistant/conversations", status_code=201)
def create_conversation(body: ConversationIn, project: Project = Depends(project_writer), principal: Principal = Depends(require_user),
                        db: Session = Depends(get_db)):
    conv = AssistantConversation(project_id=project.id, user_id=principal.user.id, title=body.title)
    db.add(conv)
    db.commit()
    return conversation_out(conv, with_messages=True)


@router.get("/assistant/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    conv, _ = _conv(db, principal, conversation_id)
    return conversation_out(conv, with_messages=True)


def _reply(db: Session, conv: AssistantConversation, content: str, payload: dict) -> AssistantMessage:
    msg = AssistantMessage(conversation_id=conv.id, role="assistant", content=content, payload=payload)
    db.add(msg)
    return msg


def _last_payload(conv: AssistantConversation, kind: str, key: Optional[str] = None) -> Optional[AssistantMessage]:
    for m in reversed(conv.messages):
        if m.role == "assistant" and m.payload.get("kind") == kind and (key is None or m.payload.get(key)):
            return m
    return None


def _store_credentials(db: Session, project: Project, text: str) -> tuple[str, list[str]]:
    """Save credentials typed into the chat as environment variables and redact them from the message."""
    env = default_environment(db, project)
    stored: list[str] = []
    if env is None:
        return text, stored

    def repl(m: re.Match) -> str:
        raw_key = m.group(1).lower().replace(" ", "_").replace("-", "_")
        key = {"user_name": "username", "login": "username", "email": "username", "apitoken": "api_token", "apikey": "api_key"}.get(raw_key, raw_key)
        key = re.sub(r"_+", "_", key)
        secret = key in SECRET_KEYS
        set_env_variable(db, env, key, m.group(2), secret)
        stored.append(key)
        return f"{m.group(1)} is {'[saved as a secret]' if secret else m.group(2)}"

    return CRED_RE.sub(repl, text), stored


def _history(conv: AssistantConversation) -> list[dict]:
    out = []
    for m in conv.messages[-12:]:
        if m.role == "user":
            out.append({"role": "user", "content": m.content})
        elif m.payload.get("kind") == "plan":
            out.append({"role": "assistant", "content": json.dumps({"title": m.payload.get("title"), "steps": m.payload.get("steps")})[:6000]})
        else:
            out.append({"role": "assistant", "content": m.content[:2000]})
    # The API requires alternating turns that start with a user message.
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


@router.post("/assistant/conversations/{conversation_id}/messages", status_code=201)
def post_message(conversation_id: uuid.UUID, body: MessageIn, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    conv, project = _conv(db, principal, conversation_id, "member")
    content, stored = _store_credentials(db, project, body.content)
    history = _history(conv)
    db.add(AssistantMessage(conversation_id=conv.id, role="user", content=content, payload={"stored_variables": stored}))
    if conv.title == "New conversation":
        conv.title = content[:80]
    low = content.lower().strip()
    if stored:
        audit.record(db, "assistant.variables_saved", organization_id=project.organization_id, project_id=project.id,
                     user_id=principal.user_id, details={"keys": stored})

    # Intent: explain the latest run in this conversation.
    if re.search(r"\b(why did|what went wrong|analy[sz]e|explain the (failure|result)|why (is|was) it failing)\b", low):
        run_msg = _last_payload(conv, "execution", "execution_id")
        if run_msg is None:
            reply = _reply(db, conv, "There is no run in this conversation yet. Save the plan and run it first.", {"kind": "info"})
        else:
            reply = _analysis_reply(db, conv, uuid.UUID(run_msg.payload["execution_id"]))
        db.commit()
        return {"messages": [message_out(reply)]}

    remainder = CRED_RE.sub("", body.content).lower()
    if stored and not re.search(r"\b(open|go to|navigate|click|verify|log ?in|sign ?in|create|test)\b", remainder):
        reply = _reply(db, conv, f"Saved {', '.join(stored)} to the project's default environment. Secrets are encrypted and never shown again.",
                       {"kind": "info", "stored_variables": stored})
        db.commit()
        return {"messages": [message_out(reply)]}

    disc = latest_discovery(db, project.id)
    pages = list(db.scalars(select(DiscoveredPage).where(DiscoveredPage.discovery_id == disc.id).order_by(DiscoveredPage.position))) if disc else []
    variables = variable_names(db, project)
    instruction = content
    previous = _last_payload(conv, "plan")
    append = bool(previous and re.match(r"^(also|and|then|additionally|after that)\b", low))
    plan = plan_instruction(instruction, pages, disc.login_result if disc else None, variables, project.base_url, history=history)
    steps = plan.steps
    if append and plan.engine == "deterministic":
        new = [s for s in plan.steps if not (s["action"] == "navigate" and s["value"] == "/" and s["description"] == "Open the application")]
        steps = list(previous.payload.get("steps", [])) + new
    report = preview_validation(db, project, "ui", steps)
    summary = plan.reply or (
        f"I turned your instructions into {len(steps)} steps." + (" Review them, then save and run the test." if steps else "")
    )
    if plan.prerequisites:
        summary += " Before running, add: " + ", ".join(p["variable"] for p in plan.prerequisites) + \
                   ". You can type them here, for example \"username is qa@example.com, password is ...\"."
    payload = {
        "kind": "plan", "title": plan.title, "steps": steps, "interpretation": plan.interpretation, "questions": plan.questions,
        "prerequisites": plan.prerequisites, "warnings": plan.warnings, "engine": plan.engine, "model": plan.model,
        "validation": {"status": report.status, "messages": report.messages}, "discovery_id": str(disc.id) if disc else None,
    }
    reply = _reply(db, conv, summary, payload)
    db.commit()
    return {"messages": [message_out(reply)]}


@router.post("/assistant/messages/{message_id}/save", status_code=201)
def save_plan(message_id: uuid.UUID, body: SavePlanIn, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    msg = db.get(AssistantMessage, message_id)
    if msg is None or msg.payload.get("kind") != "plan":
        raise HTTPException(404, "Plan not found")
    conv, project = _conv(db, principal, msg.conversation_id, "member")
    steps = body.steps if body.steps is not None else msg.payload.get("steps", [])
    if not steps:
        raise HTTPException(422, "The plan has no steps to save")
    try:
        case = create_test_case(db, project, title=body.title or msg.payload.get("title") or "Assistant test", steps=steps,
                                description="Created by the AI Test Assistant from: " + (conv.title or "")[:200],
                                category="functional", priority="medium", status="draft", source="assistant",
                                source_ref=str(conv.id), expectation_basis="specified", created_by=principal.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    msg.payload = {**msg.payload, "test_case_id": str(case.id), "steps": steps}
    _reply(db, conv, f"Saved the test \"{case.title}\". Validation: {case.validation_status}.",
           {"kind": "saved", "test_case_id": str(case.id), "validation_status": case.validation_status})
    audit.record(db, "test_case.created", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="test_case", resource_id=case.id, details={"source": "assistant"})
    db.commit()
    return test_case_out(db, case)


@router.post("/assistant/conversations/{conversation_id}/run", status_code=202)
def run_from_chat(conversation_id: uuid.UUID, body: RunPlanIn, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    conv, project = _conv(db, principal, conversation_id, "member")
    case = db.get(TestCase, body.test_case_id)
    if case is None or case.project_id != project.id:
        raise HTTPException(404, "Test case not found")
    execution = create_execution(db, project, principal, RunIn(test_case_ids=[case.id], trigger="assistant",
                                                               browser=body.browser if body.browser in ("chromium", "firefox", "webkit") else "chromium"))
    msg = _reply(db, conv, f"Started a run of \"{case.title}\". Results appear below when it finishes.",
                 {"kind": "execution", "execution_id": str(execution.id), "test_case_id": str(case.id)})
    db.commit()
    db.refresh(execution)
    return {"execution": execution_out(execution), "message": message_out(msg)}


def _analysis_reply(db: Session, conv: AssistantConversation, execution_id: uuid.UUID) -> AssistantMessage:
    execution = db.get(TestExecution, execution_id)
    if execution.status in ("queued", "running", "cancelling"):
        return _reply(db, conv, f"The run is still {execution.status}. Ask again when it has finished.", {"kind": "info"})
    results = list(db.scalars(select(TestResult).where(TestResult.execution_id == execution.id)))
    failed = [r for r in results if r.status in ("failed", "error", "flaky")]
    if not failed:
        text = f"The run {execution.status}: {execution.passed} of {execution.total} tests passed. There is nothing to analyse."
        items: list[dict] = []
    else:
        parts, items = [], []
        for r in failed:
            label = CATEGORIES.get(r.failure_category or "unknown", "Unknown")
            ev = r.failure_evidence or {}
            parts.append(f"\"{r.test_title}\": {label} ({int((r.failure_confidence or 0) * 100)}% confidence). {r.failure_summary or ''}")
            items.append({"result_id": str(r.id), "title": r.test_title, "category": label, "confidence": r.failure_confidence,
                          "summary": r.failure_summary, "verified": ev.get("verified", []), "hypotheses": ev.get("hypotheses", []),
                          "next_actions": ev.get("next_actions", [])})
        text = "Here is what the run shows. Verified facts come from the run itself; hypotheses are interpretations.\n" + "\n".join(parts)
    return _reply(db, conv, text, {"kind": "analysis", "execution_id": str(execution.id), "items": items})
