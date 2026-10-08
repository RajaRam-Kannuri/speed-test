"""AI generation jobs (run in the worker): turn discoveries / API collections into test cases."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, update

from ..agents import api_planner, website_planner
from ..agents.llm import LLMUnavailable, get_provider
from ..db import SessionLocal
from ..models import AIGenerationJob, ApiCollection, ApiEndpoint, DiscoveredPage, Project, SiteDiscovery, TestCase, utcnow
from .testcases import create_test_case

log = logging.getLogger("lorvenlax.generation")


def run_generation_job(job_id: uuid.UUID) -> str:
    db = SessionLocal()
    try:
        claimed = db.execute(update(AIGenerationJob).where(AIGenerationJob.id == job_id, AIGenerationJob.status == "queued")
                             .values(status="running")).rowcount
        db.commit()
        if not claimed:
            return "skipped"
        job = db.get(AIGenerationJob, job_id)
        project = db.get(Project, job.project_id)
        request: dict[str, Any] = dict(job.result_summary.get("request", {}))
        use_ai = bool(request.get("use_ai", True))
        created: list[TestCase] = []
        ai_info: dict[str, Any] = {"used": False}

        if job.kind == "website_plan":
            disc = db.get(SiteDiscovery, uuid.UUID(job.source_ref))
            pages = list(db.scalars(select(DiscoveredPage).where(DiscoveredPage.discovery_id == disc.id).order_by(DiscoveredPage.position)))
            planned = website_planner.plan_from_discovery(disc, pages)
            if use_ai and get_provider().name != "deterministic":
                try:
                    extra, meta = website_planner.ai_plan(disc, pages, [p.title for p in planned])
                    planned += extra
                    ai_info = {"used": True, **meta, "added": len(extra)}
                    job.engine, job.model = "anthropic", meta.get("model")
                    job.input_tokens, job.output_tokens = meta.get("input_tokens"), meta.get("output_tokens")
                except LLMUnavailable as exc:
                    ai_info = {"used": False, "error": str(exc)}
            for p in planned:
                created.append(create_test_case(db, project, title=p.title, description=p.description, kind="ui",
                                                category=p.category, priority=p.priority, status="generated",
                                                source="website_ai", source_ref=str(disc.id), expectation_basis=p.expectation_basis,
                                                tags=p.tags + ([] if p.engine == "deterministic" else ["ai"]), steps=p.steps,
                                                created_by=job.created_by))

        elif job.kind == "api_plan":
            coll = db.get(ApiCollection, uuid.UUID(job.source_ref))
            endpoints = list(db.scalars(select(ApiEndpoint).where(ApiEndpoint.collection_id == coll.id)))
            wanted = {uuid.UUID(i) for i in request.get("endpoint_ids") or []}
            ctx = api_planner.ApiPlanContext(endpoints, coll.security_schemes)
            planned_api: list[tuple[Any, ApiEndpoint | None]] = []
            for ep in endpoints:
                if wanted and ep.id not in wanted:
                    continue
                planned_api += [(t, ep) for t in api_planner.plan_endpoint(ctx, ep)]
            if use_ai and get_provider().name != "deterministic":
                try:
                    extra, meta = api_planner.ai_plan(ctx, [t.title for t, _ in planned_api])
                    planned_api += [(t, None) for t in extra]
                    ai_info = {"used": True, **meta, "added": len(extra)}
                    job.engine, job.model = "anthropic", meta.get("model")
                    job.input_tokens, job.output_tokens = meta.get("input_tokens"), meta.get("output_tokens")
                except LLMUnavailable as exc:
                    ai_info = {"used": False, "error": str(exc)}
            for t, ep in planned_api:
                created.append(create_test_case(db, project, title=t.title, description=t.description, kind="api",
                                                category=t.category, priority=t.priority, status="generated", source="api_ai",
                                                source_ref=str(ep.id) if ep else str(coll.id), expectation_basis=t.expectation_basis,
                                                tags=t.tags, steps=t.steps, created_by=job.created_by))
        else:
            raise ValueError(f"Unknown job kind {job.kind}")

        job.status = "completed"
        job.finished_at = utcnow()
        job.result_summary = {
            "request": request, "created": len(created), "test_case_ids": [str(c.id) for c in created],
            "invalid": sum(1 for c in created if c.validation_status == "invalid"), "ai": ai_info,
        }
        db.commit()
        return "completed"
    except Exception as exc:  # noqa: BLE001
        log.exception("generation job %s failed", job_id)
        db.rollback()
        job = db.get(AIGenerationJob, job_id)
        if job is not None:
            job.status, job.error_message, job.finished_at = "failed", str(exc)[:1000], utcnow()
            db.commit()
        return "failed"
    finally:
        db.close()
