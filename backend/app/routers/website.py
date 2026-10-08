"""Test My Website: authorised discovery -> generated scenarios."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, client_ip, get_principal, load_project, project_reader, project_writer
from ..models import AIGenerationJob, Environment, Project, SiteDiscovery, utcnow
from ..security.ssrf import TargetNotAllowed, check_url
from ..services import audit, ratelimit
from ..services.environments import default_environment
from ..worker import enqueue, run_discovery_task, run_generation_task
from .projects import set_env_variable
from .serializers import discovery_out, job_out

router = APIRouter(tags=["website testing"])


class DiscoveryIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    authorized: bool = Field(description="The user confirms they are authorised to test this website")
    max_pages: int = Field(default=15, ge=1, le=50)
    max_depth: int = Field(default=2, ge=0, le=5)
    login_url: Optional[str] = Field(default=None, max_length=2000)
    username: Optional[str] = Field(default=None, max_length=300)
    password: Optional[str] = Field(default=None, max_length=300)
    environment_id: Optional[uuid.UUID] = None


class GenerateIn(BaseModel):
    use_ai: bool = True


@router.post("/projects/{project_id}/discoveries", status_code=202)
def start_discovery(body: DiscoveryIn, request: Request, project: Project = Depends(project_writer),
                    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not body.authorized:
        raise HTTPException(422, "Confirm that you are authorised to test this website before continuing.")
    if principal.user is None:
        raise HTTPException(403, "Website discovery must be started by a signed-in user")
    url = body.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    try:
        check_url(url)
        if body.login_url and body.login_url.startswith("http"):
            check_url(body.login_url)
    except TargetNotAllowed as exc:
        raise HTTPException(422, f"This address cannot be tested: {exc}")
    ratelimit.hit(f"discovery:{project.organization_id}", get_settings().rate_limit_jobs_per_minute)

    env = None
    if body.environment_id:
        env = db.get(Environment, body.environment_id)
        if env is None or env.project_id != project.id:
            raise HTTPException(404, "Environment not found")
    env = env or default_environment(db, project)
    uses_login = bool(body.username and body.password)
    if uses_login:
        set_env_variable(db, env, "username", body.username, False)
        set_env_variable(db, env, "password", body.password, True)
    elif body.login_url:
        uses_login = True  # use credentials already stored in the environment

    disc = SiteDiscovery(project_id=project.id, url=url, max_pages=body.max_pages, max_depth=body.max_depth,
                         uses_login=uses_login, login_url=body.login_url, environment_id=env.id if env else None,
                         authorization_confirmed_by=principal.user.id, authorization_confirmed_at=utcnow())
    db.add(disc)
    db.flush()
    audit.record(db, "discovery.started", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="discovery", resource_id=disc.id,
                 details={"url": url, "authorization_confirmed": True, "uses_login": uses_login, "max_pages": body.max_pages},
                 ip_address=client_ip(request))
    db.commit()
    enqueue(run_discovery_task, str(disc.id))
    db.refresh(disc)
    return discovery_out(disc)


@router.get("/projects/{project_id}/discoveries")
def list_discoveries(project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    return [discovery_out(d) for d in db.scalars(select(SiteDiscovery).where(SiteDiscovery.project_id == project.id)
                                                 .order_by(SiteDiscovery.created_at.desc()).limit(20))]


def _discovery(db: Session, principal: Principal, discovery_id: uuid.UUID, minimum: str = "viewer") -> tuple[SiteDiscovery, Project]:
    disc = db.get(SiteDiscovery, discovery_id)
    if disc is None:
        raise HTTPException(404, "Discovery not found")
    return disc, load_project(db, principal, disc.project_id, minimum)


@router.get("/discoveries/{discovery_id}")
def get_discovery(discovery_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    disc, _ = _discovery(db, principal, discovery_id)
    return discovery_out(disc, with_pages=disc.status == "completed")


@router.post("/discoveries/{discovery_id}/generate", status_code=202)
def generate(discovery_id: uuid.UUID, body: GenerateIn, request: Request, principal: Principal = Depends(get_principal),
             db: Session = Depends(get_db)):
    disc, project = _discovery(db, principal, discovery_id, "member")
    if disc.status != "completed":
        raise HTTPException(409, "Discovery has not completed yet")
    job = AIGenerationJob(project_id=project.id, kind="website_plan", source_ref=str(disc.id), engine="deterministic",
                          created_by=principal.user_id, result_summary={"request": {"use_ai": body.use_ai}})
    db.add(job)
    audit.record(db, "generation.requested", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="discovery", resource_id=disc.id, ip_address=client_ip(request))
    db.commit()
    enqueue(run_generation_task, str(job.id))
    db.refresh(job)
    return job_out(job)


@router.get("/generation-jobs/{job_id}")
def get_job(job_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    job = db.get(AIGenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    load_project(db, principal, job.project_id, "viewer")
    return job_out(job)
