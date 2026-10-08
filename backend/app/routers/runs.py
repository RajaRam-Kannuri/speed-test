from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..agents.reporting import allure_zip, execution_summary, recommendations, render_html
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, client_ip, get_principal, load_project, project_reader, project_writer
from ..models import (
    Environment,
    HealingSuggestion,
    Organization,
    Project,
    SuiteItem,
    TestArtifact,
    TestCase,
    TestExecution,
    TestResult,
    TestStep,
    TestSuite,
    utcnow,
)
from ..services import audit, ratelimit
from ..services.storage import get_storage
from ..services.testcases import run_validation
from ..worker import enqueue, run_execution_task
from .serializers import artifact_out, execution_out, healing_out, result_out

router = APIRouter(tags=["runs"])


class RunIn(BaseModel):
    test_case_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    suite_id: Optional[uuid.UUID] = None
    environment_id: Optional[uuid.UUID] = None
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    workers: int = Field(default=1, ge=1, le=8)
    retries: int = Field(default=0, ge=0, le=3)
    timeout_ms: int = Field(default=30_000, ge=5_000, le=300_000)
    capture_video: Literal["off", "on", "retain-on-failure"] = "retain-on-failure"
    capture_trace: Literal["off", "on", "retain-on-failure"] = "retain-on-failure"
    capture_screenshot: Literal["off", "on", "only-on-failure"] = "on"
    idempotency_key: Optional[str] = Field(default=None, max_length=100)
    trigger: Literal["manual", "ci", "assistant", "api"] = "manual"


def create_execution(db: Session, project: Project, principal: Principal, body: RunIn) -> TestExecution:
    settings = get_settings()
    ratelimit.hit(f"runs:{project.organization_id}", settings.rate_limit_jobs_per_minute)
    if body.idempotency_key:
        existing = db.scalar(select(TestExecution).where(TestExecution.project_id == project.id,
                                                         TestExecution.idempotency_key == body.idempotency_key))
        if existing:
            return existing
    ids = list(body.test_case_ids)
    if body.suite_id:
        suite = db.get(TestSuite, body.suite_id)
        if suite is None or suite.project_id != project.id:
            raise HTTPException(404, "Suite not found")
        ids += list(db.scalars(select(SuiteItem.test_case_id).where(SuiteItem.suite_id == suite.id).order_by(SuiteItem.position)))
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(422, "Choose at least one test to run")
    cases = list(db.scalars(select(TestCase).where(TestCase.project_id == project.id, TestCase.id.in_(ids))))
    if len(cases) != len(ids):
        raise HTTPException(404, "Some tests were not found in this project")
    env = None
    if body.environment_id:
        env = db.get(Environment, body.environment_id)
        if env is None or env.project_id != project.id:
            raise HTTPException(404, "Environment not found")

    invalid = []
    for c in cases:
        report = run_validation(db, project, c)
        if not report.ok:
            invalid.append({"id": str(c.id), "title": c.title,
                            "errors": [m["message"] for m in report.messages if m["level"] == "error"][:3]})
    if invalid:
        db.commit()
        raise HTTPException(422, {"message": "Some tests have validation errors. Fix them before running.", "tests": invalid})

    org = db.get(Organization, project.organization_id)
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count(TestResult.id)).join(TestExecution, TestExecution.id == TestResult.execution_id)
                     .join(Project, Project.id == TestExecution.project_id)
                     .where(Project.organization_id == org.id, TestResult.created_at >= month_start)) or 0
    if used + len(cases) > org.monthly_test_run_quota:
        raise HTTPException(402, f"Monthly test run quota reached ({used}/{org.monthly_test_run_quota}).")

    execution = TestExecution(
        project_id=project.id, environment_id=env.id if env else None, suite_id=body.suite_id,
        triggered_by=principal.user_id, trigger="ci" if principal.api_token else body.trigger,
        idempotency_key=body.idempotency_key, browser=body.browser, headless=body.headless, workers=body.workers,
        retries=body.retries, timeout_ms=body.timeout_ms, capture_video=body.capture_video,
        capture_trace=body.capture_trace, capture_screenshot=body.capture_screenshot, total=len(cases),
    )
    db.add(execution)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(TestExecution).where(TestExecution.project_id == project.id,
                                                     TestExecution.idempotency_key == body.idempotency_key))
    for c in cases:
        db.add(TestResult(execution_id=execution.id, test_case_id=c.id, test_title=c.title, test_case_version=c.version,
                          browser=body.browser, status="queued"))
    audit.record(db, "execution.created", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="execution", resource_id=execution.id,
                 details={"tests": len(cases), "browser": body.browser, "trigger": execution.trigger})
    db.commit()
    execution.task_id = enqueue(run_execution_task, str(execution.id))
    db.commit()
    return execution


@router.post("/projects/{project_id}/executions", status_code=202)
def create_run(body: RunIn, project: Project = Depends(project_writer), principal: Principal = Depends(get_principal),
               db: Session = Depends(get_db)):
    execution = create_execution(db, project, principal, body)
    db.refresh(execution)
    return execution_out(execution)


@router.get("/projects/{project_id}/executions")
def list_runs(project: Project = Depends(project_reader), db: Session = Depends(get_db), limit: int = 50, status: Optional[str] = None):
    stmt = select(TestExecution).where(TestExecution.project_id == project.id)
    if status:
        stmt = stmt.where(TestExecution.status == status)
    return [execution_out(e) for e in db.scalars(stmt.order_by(TestExecution.created_at.desc()).limit(min(limit, 200)))]


def _execution(db: Session, principal: Principal, execution_id: uuid.UUID, minimum: str = "viewer") -> tuple[TestExecution, Project]:
    execution = db.get(TestExecution, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found")
    project = load_project(db, principal, execution.project_id, minimum)
    return execution, project


@router.get("/executions/{execution_id}")
def get_run(execution_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    execution, _ = _execution(db, principal, execution_id)
    results = list(db.scalars(select(TestResult).where(TestResult.execution_id == execution.id).order_by(TestResult.test_title)))
    reports = db.scalars(select(TestArtifact).where(TestArtifact.execution_id == execution.id, TestArtifact.kind == "report")).all()
    out = execution_out(execution)
    out.update({"results": [result_out(db, r) for r in results], "summary": execution_summary(execution, results),
                "recommendations": recommendations(results) if execution.status not in ("queued", "running") else [],
                "reports": [artifact_out(a) for a in reports]})
    return out


@router.post("/executions/{execution_id}/cancel")
def cancel_run(execution_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    execution, project = _execution(db, principal, execution_id, "member")
    if execution.status == "queued":
        execution.status = "cancelled"
        execution.finished_at = utcnow()
        for r in execution.results:
            if r.status == "queued":
                r.status = "cancelled"
    elif execution.status == "running":
        execution.status = "cancelling"
    else:
        raise HTTPException(409, f"Execution is already {execution.status}")
    audit.record(db, "execution.cancelled", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="execution", resource_id=execution.id)
    db.commit()
    return execution_out(execution)


@router.get("/results/{result_id}")
def get_result(result_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    r = db.get(TestResult, result_id)
    if r is None:
        raise HTTPException(404, "Result not found")
    _execution(db, principal, r.execution_id)
    return result_out(db, r, detail=True)


class HealingDecision(BaseModel):
    decision: Literal["accept", "reject"]


@router.post("/healing-suggestions/{suggestion_id}")
def decide_healing(suggestion_id: uuid.UUID, body: HealingDecision, request: Request, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_db)):
    hs = db.get(HealingSuggestion, suggestion_id)
    if hs is None:
        raise HTTPException(404, "Suggestion not found")
    project = load_project(db, principal, hs.project_id, "member")
    if hs.status != "pending":
        raise HTTPException(409, f"This suggestion was already {hs.status}")
    hs.status = "accepted" if body.decision == "accept" else "rejected"
    hs.decided_by, hs.decided_at = principal.user_id, utcnow()
    details = {"original": hs.original_target, "suggested": hs.suggested_target, "confidence": hs.confidence}
    if hs.status == "accepted":
        step = db.get(TestStep, hs.test_step_id) if hs.test_step_id else None
        if step is None:
            raise HTTPException(409, "The step this suggestion refers to no longer exists")
        case = db.get(TestCase, step.test_case_id)
        if case.project_id != project.id:
            raise HTTPException(404, "Suggestion not found")
        # Only the locator changes; action, value and assertion intent stay as they were.
        step.target = hs.suggested_target
        case.version += 1
        details.update({"test_case_id": str(case.id), "step_position": step.position + 1, "new_version": case.version})
        for other in db.scalars(select(HealingSuggestion).where(HealingSuggestion.result_id == hs.result_id,
                                                                HealingSuggestion.id != hs.id, HealingSuggestion.status == "pending")):
            other.status = "rejected"
        run_validation(db, project, case)
    audit.record(db, f"healing.{hs.status}", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="healing_suggestion", resource_id=hs.id, details=details,
                 ip_address=client_ip(request))
    db.commit()
    return healing_out(hs)


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db), download: bool = False):
    art = db.get(TestArtifact, artifact_id)
    if art is None:
        raise HTTPException(404, "Artifact not found")
    load_project(db, principal, art.project_id, "viewer")
    disposition = "attachment" if download or art.kind in ("trace",) else "inline"
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in art.name)[:100] or "artifact"
    ext = {"screenshot": ".png", "video": ".webm", "trace": ".zip"}.get(art.kind, "")
    headers = {"Content-Disposition": f'{disposition}; filename="{safe_name}{ext if not safe_name.endswith(ext) else ""}"',
               "Cache-Control": "private, max-age=300", "Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"}
    return StreamingResponse(get_storage().open(art.storage_key), media_type=art.content_type, headers=headers)


@router.get("/executions/{execution_id}/report")
def report(execution_id: uuid.UUID, format: Literal["html", "pdf", "allure"] = "html",
           principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    execution, _ = _execution(db, principal, execution_id)
    if execution.status in ("queued", "running", "cancelling"):
        raise HTTPException(409, "The execution has not finished yet")
    name = f"lorvenlax-report-{str(execution.id)[:8]}"
    if format == "allure":
        return Response(allure_zip(db, execution), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}-allure-results.zip"'})
    if format == "pdf":
        art = db.scalar(select(TestArtifact).where(TestArtifact.execution_id == execution.id, TestArtifact.name == "report.pdf"))
        if art is None:
            raise HTTPException(404, "The PDF report is not available for this execution")
        return StreamingResponse(get_storage().open(art.storage_key), media_type="application/pdf",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return Response(render_html(db, execution), media_type="text/html",
                    headers={"Content-Disposition": f'attachment; filename="{name}.html"'})
