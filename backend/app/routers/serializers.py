"""Response shapes. Secret values are never serialized."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents.failure_analysis import CATEGORIES
from ..models import (
    AIGenerationJob,
    ApiCollection,
    ApiEndpoint,
    AssistantConversation,
    AssistantMessage,
    DiscoveredPage,
    Environment,
    HealingSuggestion,
    Membership,
    Organization,
    Project,
    SiteDiscovery,
    TestArtifact,
    TestCase,
    TestExecution,
    TestResult,
    TestStep,
    TestSuite,
    User,
)


def iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def user_out(db: Session, user: User) -> dict[str, Any]:
    rows = db.execute(
        select(Membership, Organization).join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id).order_by(Organization.created_at)
    ).all()
    return {
        "id": str(user.id), "email": user.email, "name": user.name,
        "organizations": [{"id": str(o.id), "name": o.name, "slug": o.slug, "role": m.role, "plan": o.plan} for m, o in rows],
    }


def project_out(db: Session, p: Project) -> dict[str, Any]:
    return {
        "id": str(p.id), "organization_id": str(p.organization_id), "name": p.name, "description": p.description,
        "base_url": p.base_url, "created_at": iso(p.created_at),
        "test_count": db.scalar(select(func.count(TestCase.id)).where(TestCase.project_id == p.id, TestCase.status != "archived")) or 0,
        "last_execution": _last_exec(db, p),
    }


def _last_exec(db: Session, p: Project) -> Optional[dict]:
    e = db.scalar(select(TestExecution).where(TestExecution.project_id == p.id).order_by(TestExecution.created_at.desc()).limit(1))
    return {"id": str(e.id), "status": e.status, "created_at": iso(e.created_at), "passed": e.passed, "failed": e.failed, "total": e.total} if e else None


def environment_out(env: Environment) -> dict[str, Any]:
    return {
        "id": str(env.id), "name": env.name, "base_url": env.base_url, "is_default": env.is_default,
        "variables": [{"id": str(v.id), "key": v.key, "is_secret": v.is_secret, "value": None if v.is_secret else v.value,
                       "has_value": bool(v.secret_ciphertext) if v.is_secret else v.value is not None}
                      for v in sorted(env.variables, key=lambda x: x.key)],
    }


def step_out(s: TestStep) -> dict[str, Any]:
    return {"id": str(s.id), "position": s.position, "action": s.action, "target": s.target, "value": s.value,
            "options": s.options or {}, "description": s.description}


def test_case_out(db: Session, c: TestCase, with_steps: bool = True) -> dict[str, Any]:
    last = db.scalar(select(TestResult).where(TestResult.test_case_id == c.id).order_by(TestResult.created_at.desc()).limit(1))
    out = {
        "id": str(c.id), "project_id": str(c.project_id), "title": c.title, "description": c.description, "kind": c.kind,
        "category": c.category, "priority": c.priority, "status": c.status, "source": c.source, "source_ref": c.source_ref,
        "expectation_basis": c.expectation_basis, "tags": c.tags or [], "validation_status": c.validation_status,
        "validation_messages": c.validation_messages or [], "version": c.version,
        "created_at": iso(c.created_at), "updated_at": iso(c.updated_at), "step_count": len(c.steps),
        "last_result": {"status": last.status, "execution_id": str(last.execution_id), "at": iso(last.created_at)} if last else None,
    }
    if with_steps:
        out["steps"] = [step_out(s) for s in c.steps]
    return out


def suite_out(db: Session, s: TestSuite) -> dict[str, Any]:
    return {"id": str(s.id), "name": s.name, "description": s.description,
            "test_case_ids": [str(i.test_case_id) for i in s.items], "created_at": iso(s.created_at)}


def execution_out(e: TestExecution) -> dict[str, Any]:
    return {
        "id": str(e.id), "project_id": str(e.project_id), "environment_id": str(e.environment_id) if e.environment_id else None,
        "suite_id": str(e.suite_id) if e.suite_id else None, "trigger": e.trigger, "status": e.status, "browser": e.browser,
        "headless": e.headless, "workers": e.workers, "retries": e.retries, "timeout_ms": e.timeout_ms,
        "capture": {"screenshot": e.capture_screenshot, "video": e.capture_video, "trace": e.capture_trace},
        "created_at": iso(e.created_at), "started_at": iso(e.started_at), "finished_at": iso(e.finished_at),
        "duration_ms": e.duration_ms, "total": e.total, "passed": e.passed, "failed": e.failed, "skipped": e.skipped,
        "flaky": e.flaky, "error_message": e.error_message,
    }


def artifact_out(a: TestArtifact) -> dict[str, Any]:
    return {"id": str(a.id), "kind": a.kind, "name": a.name, "content_type": a.content_type, "size_bytes": a.size_bytes,
            "url": f"/api/artifacts/{a.id}"}


def healing_out(h: HealingSuggestion) -> dict[str, Any]:
    return {"id": str(h.id), "result_id": str(h.result_id), "test_step_id": str(h.test_step_id) if h.test_step_id else None,
            "original_target": h.original_target, "suggested_target": h.suggested_target, "confidence": h.confidence,
            "rationale": h.rationale, "status": h.status, "decided_at": iso(h.decided_at)}


def result_out(db: Session, r: TestResult, detail: bool = False) -> dict[str, Any]:
    out = {
        "id": str(r.id), "execution_id": str(r.execution_id), "test_case_id": str(r.test_case_id) if r.test_case_id else None,
        "test_title": r.test_title, "status": r.status, "browser": r.browser, "started_at": iso(r.started_at),
        "finished_at": iso(r.finished_at), "duration_ms": r.duration_ms, "retries_used": r.retries_used,
        "error_message": r.error_message, "failed_step_index": r.failed_step_index,
        "failure": {"category": r.failure_category, "label": CATEGORIES.get(r.failure_category or "", None),
                    "confidence": r.failure_confidence, "summary": r.failure_summary, "evidence": r.failure_evidence} if r.failure_category else None,
    }
    if detail:
        out.update({
            "error_stack": r.error_stack, "step_results": r.step_results or [], "generated_code": r.generated_code, "log": r.log,
            "artifacts": [artifact_out(a) for a in r.artifacts],
            "healing_suggestions": [healing_out(h) for h in db.scalars(select(HealingSuggestion).where(HealingSuggestion.result_id == r.id).order_by(HealingSuggestion.confidence.desc()))],
        })
    return out


def page_out(p: DiscoveredPage) -> dict[str, Any]:
    return {"id": str(p.id), "url": p.url, "title": p.title, "status_code": p.status_code, "depth": p.depth,
            "requires_login": p.requires_login, "screenshot_url": f"/api/artifacts/{p.screenshot_artifact_id}" if p.screenshot_artifact_id else None,
            "headings": p.headings, "forms": p.forms, "links": [{"text": l["text"], "href": l["href"], "in_nav": l.get("in_nav")} for l in p.links],
            "buttons": [{"text": b["text"]} for b in p.buttons], "tables": p.tables,
            "counts": {"forms": len(p.forms), "links": len(p.links), "buttons": len(p.buttons), "tables": len(p.tables),
                       "fields": sum(len(f.get("fields", [])) for f in p.forms)}}


def discovery_out(d: SiteDiscovery, with_pages: bool = False) -> dict[str, Any]:
    out = {"id": str(d.id), "project_id": str(d.project_id), "url": d.url, "status": d.status, "max_pages": d.max_pages,
           "max_depth": d.max_depth, "uses_login": d.uses_login, "login_result": d.login_result, "skipped": d.skipped,
           "page_count": d.page_count, "error_message": d.error_message, "created_at": iso(d.created_at),
           "started_at": iso(d.started_at), "finished_at": iso(d.finished_at)}
    if with_pages:
        out["pages"] = [page_out(p) for p in d.pages]
    return out


def endpoint_out(e: ApiEndpoint) -> dict[str, Any]:
    return {"id": str(e.id), "method": e.method, "path": e.path, "operation_id": e.operation_id, "summary": e.summary,
            "tags": e.tags, "parameters": e.parameters, "request_schema": e.request_schema,
            "responses": {k: {"description": v.get("description"), "has_schema": bool(v.get("schema"))} for k, v in (e.responses or {}).items()},
            "requires_auth": bool(e.security)}


def collection_out(c: ApiCollection, with_endpoints: bool = False) -> dict[str, Any]:
    out = {"id": str(c.id), "name": c.name, "source_type": c.source_type, "source_url": c.source_url, "base_url": c.base_url,
           "spec_version": c.spec_version, "security_schemes": c.security_schemes, "endpoint_count": len(c.endpoints),
           "created_at": iso(c.created_at)}
    if with_endpoints:
        out["endpoints"] = [endpoint_out(e) for e in c.endpoints]
    return out


def job_out(j: AIGenerationJob) -> dict[str, Any]:
    return {"id": str(j.id), "kind": j.kind, "status": j.status, "engine": j.engine, "model": j.model,
            "source_ref": j.source_ref, "result": j.result_summary, "error_message": j.error_message,
            "created_at": iso(j.created_at), "finished_at": iso(j.finished_at)}


def message_out(m: AssistantMessage) -> dict[str, Any]:
    return {"id": str(m.id), "role": m.role, "content": m.content, "payload": m.payload, "created_at": iso(m.created_at)}


def conversation_out(c: AssistantConversation, with_messages: bool = False) -> dict[str, Any]:
    out = {"id": str(c.id), "title": c.title, "created_at": iso(c.created_at)}
    if with_messages:
        out["messages"] = [message_out(m) for m in c.messages]
    return out
