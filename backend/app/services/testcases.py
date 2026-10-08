from __future__ import annotations

import uuid
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.validation import ValidationReport, known_locators_from_pages, steps_from_dicts, steps_from_models, validate_steps
from ..models import DiscoveredPage, Project, SiteDiscovery, TestCase, TestStep
from .environments import variable_names
from .steps import ACTIONS, default_description


def latest_discovery(db: Session, project_id: uuid.UUID) -> Optional[SiteDiscovery]:
    return db.scalar(select(SiteDiscovery).where(SiteDiscovery.project_id == project_id, SiteDiscovery.status == "completed")
                     .order_by(SiteDiscovery.created_at.desc()).limit(1))


def known_locators(db: Session, project_id: uuid.UUID) -> Optional[set]:
    disc = latest_discovery(db, project_id)
    if disc is None:
        return None
    return known_locators_from_pages(db.scalars(select(DiscoveredPage).where(DiscoveredPage.discovery_id == disc.id)))


def replace_steps(case: TestCase, steps: Iterable[dict[str, Any]]) -> None:
    case.steps.clear()
    for i, s in enumerate(steps):
        action = s.get("action")
        if action not in ACTIONS:
            raise ValueError(f"Unknown action '{action}' in step {i + 1}")
        target = s.get("target") or None
        value = s.get("value")
        options = s.get("options") or {}
        case.steps.append(TestStep(
            position=i, action=action, target=target, value=None if value is None else str(value), options=options,
            description=(s.get("description") or default_description(action, target, value, options))[:500],
        ))


def run_validation(db: Session, project: Project, case: TestCase) -> ValidationReport:
    report = validate_steps(
        steps_from_models(case.steps), kind=case.kind, available_vars=variable_names(db, project),
        base_url=project.base_url, known_locators=known_locators(db, project.id) if case.kind == "ui" else None,
    )
    case.validation_status = report.status
    case.validation_messages = report.messages
    return report


def create_test_case(db: Session, project: Project, *, title: str, steps: list[dict], kind: Optional[str] = None,
                     description: str = "", category: str = "functional", priority: str = "medium", status: str = "draft",
                     source: str = "manual", source_ref: Optional[str] = None, expectation_basis: str = "confirmed",
                     tags: Optional[list[str]] = None, created_by: Optional[uuid.UUID] = None) -> TestCase:
    if kind is None:
        kind = "api" if steps and all(ACTIONS.get(s.get("action"), ACTIONS["wait_ms"]).kind != "ui" for s in steps) else "ui"
    case = TestCase(project_id=project.id, title=title[:300], description=description, kind=kind, category=category,
                    priority=priority, status=status, source=source, source_ref=source_ref,
                    expectation_basis=expectation_basis, tags=tags or [], created_by=created_by)
    db.add(case)
    replace_steps(case, steps)
    db.flush()
    run_validation(db, project, case)
    return case


def preview_validation(db: Session, project: Project, kind: str, steps: list[dict]) -> ValidationReport:
    return validate_steps(steps_from_dicts(steps), kind=kind, available_vars=variable_names(db, project), base_url=project.base_url,
                          known_locators=known_locators(db, project.id) if kind == "ui" else None)
