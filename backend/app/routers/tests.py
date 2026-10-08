from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..agents.validation import compile_check, steps_from_models
from ..db import get_db
from ..deps import Principal, client_ip, get_principal, project_reader, project_writer
from ..models import Project, SuiteItem, TestCase, TestResult, TestSuite
from ..services import audit
from ..services.codegen import generate_spec
from ..services.steps import ACTIONS, LOCATOR_STRATEGIES
from ..services.testcases import create_test_case, preview_validation, replace_steps, run_validation
from .serializers import iso, result_out, suite_out, test_case_out

router = APIRouter(tags=["tests"])

Category = Literal["functional", "negative", "boundary", "security", "ui", "smoke", "regression", "schema", "performance"]
Priority = Literal["high", "medium", "low"]


class StepIn(BaseModel):
    action: str
    target: Optional[dict[str, Any]] = None
    value: Optional[str] = Field(default=None, max_length=20_000)
    options: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", max_length=500)


class TestCaseIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    kind: Optional[Literal["ui", "api"]] = None
    category: Category = "functional"
    priority: Priority = "medium"
    tags: list[str] = Field(default_factory=list, max_length=20)
    steps: list[StepIn] = Field(default_factory=list, max_length=200)


class TestCasePatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=5000)
    category: Optional[Category] = None
    priority: Optional[Priority] = None
    status: Optional[Literal["draft", "generated", "ready", "archived"]] = None
    tags: Optional[list[str]] = None
    steps: Optional[list[StepIn]] = Field(default=None, max_length=200)


class SuiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    test_case_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class PreviewIn(BaseModel):
    kind: Literal["ui", "api"] = "ui"
    title: str = "Preview"
    steps: list[StepIn]
    compile: bool = False


def get_case(db: Session, project: Project, case_id: uuid.UUID) -> TestCase:
    case = db.get(TestCase, case_id)
    if case is None or case.project_id != project.id:
        raise HTTPException(404, "Test case not found")
    return case


@router.get("/step-actions", tags=["tests"])
def step_actions():
    """The step vocabulary, for builders and integrations."""
    return {"actions": [{"action": k, "label": v.label, "target": v.target, "value": v.value, "kind": v.kind,
                         "assertion": v.assertion, "value_label": v.value_label, "help": v.help} for k, v in ACTIONS.items()],
            "locator_strategies": list(LOCATOR_STRATEGIES)}


@router.get("/projects/{project_id}/test-cases")
def list_cases(project: Project = Depends(project_reader), db: Session = Depends(get_db),
               q: Optional[str] = None, kind: Optional[str] = None, category: Optional[str] = None,
               status: Optional[str] = None, source: Optional[str] = None, include_archived: bool = False):
    stmt = select(TestCase).where(TestCase.project_id == project.id)
    if not include_archived and status != "archived":
        stmt = stmt.where(TestCase.status != "archived")
    if q:
        stmt = stmt.where(or_(TestCase.title.ilike(f"%{q}%"), TestCase.description.ilike(f"%{q}%")))
    for col, val in ((TestCase.kind, kind), (TestCase.category, category), (TestCase.status, status), (TestCase.source, source)):
        if val:
            stmt = stmt.where(col == val)
    return [test_case_out(db, c, with_steps=False) for c in db.scalars(stmt.order_by(TestCase.created_at.desc()))]


@router.post("/projects/{project_id}/test-cases", status_code=201)
def create_case(body: TestCaseIn, request: Request, project: Project = Depends(project_writer),
                principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    try:
        case = create_test_case(db, project, title=body.title, description=body.description, kind=body.kind,
                                category=body.category, priority=body.priority, tags=body.tags, source="builder",
                                steps=[s.model_dump() for s in body.steps], status="draft", created_by=principal.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit.record(db, "test_case.created", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="test_case", resource_id=case.id, ip_address=client_ip(request))
    db.commit()
    return test_case_out(db, case)


@router.get("/projects/{project_id}/test-cases/{case_id}")
def get_case_route(case_id: uuid.UUID, project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    return test_case_out(db, get_case(db, project, case_id))


@router.patch("/projects/{project_id}/test-cases/{case_id}")
def update_case(case_id: uuid.UUID, body: TestCasePatch, request: Request, project: Project = Depends(project_writer),
                principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = get_case(db, project, case_id)
    changed = body.model_dump(exclude_none=True, exclude={"steps"})
    for k, v in changed.items():
        setattr(case, k, v)
    if body.steps is not None:
        try:
            replace_steps(case, [s.model_dump() for s in body.steps])
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if case.status == "generated":
            case.status = "draft"
    case.version += 1
    db.flush()
    run_validation(db, project, case)
    audit.record(db, "test_case.updated", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="test_case", resource_id=case.id,
                 details={"fields": sorted(changed) + (["steps"] if body.steps is not None else []), "version": case.version},
                 ip_address=client_ip(request))
    db.commit()
    return test_case_out(db, case)


@router.post("/projects/{project_id}/test-cases/{case_id}/duplicate", status_code=201)
def duplicate_case(case_id: uuid.UUID, request: Request, project: Project = Depends(project_writer),
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    src = get_case(db, project, case_id)
    copy = create_test_case(db, project, title=f"{src.title} (copy)"[:300], description=src.description, kind=src.kind,
                            category=src.category, priority=src.priority, tags=list(src.tags or []), source=src.source,
                            source_ref=src.source_ref, expectation_basis=src.expectation_basis, status="draft",
                            steps=[{"action": s.action, "target": s.target, "value": s.value, "options": s.options,
                                    "description": s.description} for s in src.steps], created_by=principal.user_id)
    audit.record(db, "test_case.duplicated", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="test_case", resource_id=copy.id, details={"from": str(src.id)}, ip_address=client_ip(request))
    db.commit()
    return test_case_out(db, copy)


@router.delete("/projects/{project_id}/test-cases/{case_id}", status_code=204)
def delete_case(case_id: uuid.UUID, request: Request, project: Project = Depends(project_writer),
                principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = get_case(db, project, case_id)
    audit.record(db, "test_case.deleted", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="test_case", resource_id=case.id, details={"title": case.title}, ip_address=client_ip(request))
    db.delete(case)
    db.commit()


@router.post("/projects/{project_id}/test-cases/{case_id}/validate")
def validate_case(case_id: uuid.UUID, project: Project = Depends(project_writer), db: Session = Depends(get_db),
                  compile: bool = Query(True, description="Also load the generated code with Playwright")):
    case = get_case(db, project, case_id)
    report = run_validation(db, project, case)
    compiled, output = None, None
    if compile and report.ok:
        compiled, output = compile_check(case.title, steps_from_models(case.steps))
        if not compiled:
            report.add("error", "compile_failed", "The generated Playwright code failed to load: " + output[-300:])
            case.validation_status, case.validation_messages = report.status, report.messages
    if report.ok and case.status in ("draft", "generated"):
        case.status = "ready"
    db.commit()
    return {"status": report.status, "messages": report.messages, "compiled": compiled, "compile_output": output,
            "test_case": test_case_out(db, case)}


@router.post("/projects/{project_id}/validate-steps")
def validate_preview(body: PreviewIn, project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    """Validate unsaved steps (used by the builder and the assistant before saving)."""
    steps = [s.model_dump() for s in body.steps]
    report = preview_validation(db, project, body.kind, steps)
    out: dict[str, Any] = {"status": report.status, "messages": report.messages}
    if body.compile and report.ok:
        from ..agents.validation import steps_from_dicts

        ok, output = compile_check(body.title, steps_from_dicts(steps))
        out.update({"compiled": ok, "compile_output": output})
    return out


@router.get("/projects/{project_id}/test-cases/{case_id}/code")
def case_code(case_id: uuid.UUID, project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    case = get_case(db, project, case_id)
    return {"language": "typescript", "framework": "playwright",
            "code": generate_spec(str(case.id)[:8], case.title, list(case.steps), "@lorvenlax/runtime")}


@router.get("/projects/{project_id}/test-cases/{case_id}/history")
def case_history(case_id: uuid.UUID, project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    case = get_case(db, project, case_id)
    rows = db.scalars(select(TestResult).where(TestResult.test_case_id == case.id).order_by(TestResult.created_at.desc()).limit(50))
    return [result_out(db, r) for r in rows]


# --------------------------------------------------------------------------- suites


@router.get("/projects/{project_id}/suites")
def list_suites(project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    return [suite_out(db, s) for s in db.scalars(select(TestSuite).where(TestSuite.project_id == project.id).order_by(TestSuite.name))]


def _set_suite_items(db: Session, project: Project, suite: TestSuite, ids: list[uuid.UUID]) -> None:
    valid = set(db.scalars(select(TestCase.id).where(TestCase.project_id == project.id, TestCase.id.in_(ids))))
    missing = [str(i) for i in ids if i not in valid]
    if missing:
        raise HTTPException(404, f"Test cases not found in this project: {', '.join(missing[:5])}")
    suite.items.clear()
    db.flush()
    seen: set[uuid.UUID] = set()
    for pos, i in enumerate(ids):
        if i not in seen:
            seen.add(i)
            suite.items.append(SuiteItem(test_case_id=i, position=pos))


@router.post("/projects/{project_id}/suites", status_code=201)
def create_suite(body: SuiteIn, request: Request, project: Project = Depends(project_writer),
                 principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    suite = TestSuite(project_id=project.id, name=body.name.strip(), description=body.description)
    db.add(suite)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A suite with this name already exists")
    _set_suite_items(db, project, suite, body.test_case_ids)
    audit.record(db, "suite.created", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="suite", resource_id=suite.id, ip_address=client_ip(request))
    db.commit()
    return suite_out(db, suite)


@router.put("/projects/{project_id}/suites/{suite_id}")
def update_suite(suite_id: uuid.UUID, body: SuiteIn, project: Project = Depends(project_writer), db: Session = Depends(get_db)):
    suite = db.get(TestSuite, suite_id)
    if suite is None or suite.project_id != project.id:
        raise HTTPException(404, "Suite not found")
    suite.name, suite.description = body.name.strip(), body.description
    _set_suite_items(db, project, suite, body.test_case_ids)
    db.commit()
    return suite_out(db, suite)


@router.delete("/projects/{project_id}/suites/{suite_id}", status_code=204)
def delete_suite(suite_id: uuid.UUID, project: Project = Depends(project_writer), db: Session = Depends(get_db)):
    suite = db.get(TestSuite, suite_id)
    if suite is None or suite.project_id != project.id:
        raise HTTPException(404, "Suite not found")
    db.delete(suite)
    db.commit()
