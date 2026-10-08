from __future__ import annotations

import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, client_ip, get_principal, project_admin, project_reader, project_writer, require_org_role
from ..models import Environment, EnvironmentVariable, Project
from ..security.crypto import encrypt
from ..security.ssrf import TargetNotAllowed, check_url
from ..services import audit
from .serializers import environment_out, project_out

router = APIRouter(tags=["projects"])


def _check_base_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip().rstrip("/")
    try:
        check_url(url, resolve=False)
    except TargetNotAllowed as exc:
        raise HTTPException(422, str(exc))
    return url


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    base_url: Optional[str] = Field(default=None, max_length=2000)


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    base_url: Optional[str] = Field(default=None, max_length=2000)


class EnvironmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: Optional[str] = Field(default=None, max_length=2000)
    is_default: bool = False


class VariableIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(max_length=10_000)
    is_secret: bool = False

    @field_validator("key")
    @classmethod
    def key_format(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][\w.-]*", v):
            raise ValueError("Use letters, numbers, dots, dashes and underscores; start with a letter")
        return v


@router.get("/organizations/{org_id}/projects")
def list_projects(org_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "viewer")
    q = select(Project).where(Project.organization_id == org_id)
    if principal.api_token is not None and principal.api_token.project_id:
        q = q.where(Project.id == principal.api_token.project_id)
    return [project_out(db, p) for p in db.scalars(q.order_by(Project.created_at.desc()))]


@router.post("/organizations/{org_id}/projects", status_code=201)
def create_project(org_id: uuid.UUID, body: ProjectIn, request: Request, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "member")
    project = Project(organization_id=org_id, name=body.name.strip(), description=body.description,
                      base_url=_check_base_url(body.base_url), created_by=principal.user_id)
    db.add(project)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A project with this name already exists")
    db.add(Environment(project_id=project.id, name="Default", base_url=project.base_url, is_default=True))
    audit.record(db, "project.created", organization_id=org_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="project", resource_id=project.id, ip_address=client_ip(request))
    db.commit()
    return project_out(db, project)


@router.get("/projects/{project_id}")
def get_project(project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    return project_out(db, project)


@router.patch("/projects/{project_id}")
def update_project(body: ProjectPatch, request: Request, project: Project = Depends(project_writer),
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if body.name is not None:
        project.name = body.name.strip()
    if body.description is not None:
        project.description = body.description
    if body.base_url is not None:
        project.base_url = _check_base_url(body.base_url)
    audit.record(db, "project.updated", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="project", resource_id=project.id, details=body.model_dump(exclude_none=True), ip_address=client_ip(request))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A project with this name already exists")
    return project_out(db, project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(request: Request, project: Project = Depends(project_admin), principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_db)):
    audit.record(db, "project.deleted", organization_id=project.organization_id, user_id=principal.user_id,
                 resource_type="project", resource_id=project.id, details={"name": project.name}, ip_address=client_ip(request))
    db.delete(project)
    db.commit()


# --------------------------------------------------------------------------- environments


def _env(db: Session, project: Project, env_id: uuid.UUID) -> Environment:
    env = db.get(Environment, env_id)
    if env is None or env.project_id != project.id:
        raise HTTPException(404, "Environment not found")
    return env


@router.get("/projects/{project_id}/environments")
def list_envs(project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    return [environment_out(e) for e in db.scalars(select(Environment).where(Environment.project_id == project.id).order_by(Environment.created_at))]


@router.post("/projects/{project_id}/environments", status_code=201)
def create_env(body: EnvironmentIn, request: Request, project: Project = Depends(project_writer),
               principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    env = Environment(project_id=project.id, name=body.name.strip(), base_url=_check_base_url(body.base_url), is_default=body.is_default)
    if body.is_default:
        for other in db.scalars(select(Environment).where(Environment.project_id == project.id)):
            other.is_default = False
    db.add(env)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An environment with this name already exists")
    audit.record(db, "environment.created", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="environment", resource_id=env.id, ip_address=client_ip(request))
    db.commit()
    return environment_out(env)


@router.patch("/projects/{project_id}/environments/{env_id}")
def update_env(env_id: uuid.UUID, body: EnvironmentIn, request: Request, project: Project = Depends(project_writer),
               principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    env = _env(db, project, env_id)
    env.name, env.base_url = body.name.strip(), _check_base_url(body.base_url)
    if body.is_default:
        for other in db.scalars(select(Environment).where(Environment.project_id == project.id)):
            other.is_default = other.id == env.id
    audit.record(db, "environment.updated", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="environment", resource_id=env.id, ip_address=client_ip(request))
    db.commit()
    return environment_out(env)


@router.put("/projects/{project_id}/environments/{env_id}/variables")
def set_variable(env_id: uuid.UUID, body: VariableIn, request: Request, project: Project = Depends(project_writer),
                 principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    env = _env(db, project, env_id)
    set_env_variable(db, env, body.key, body.value, body.is_secret)
    audit.record(db, "environment.variable_set", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="environment", resource_id=env.id,
                 details={"key": body.key, "is_secret": body.is_secret}, ip_address=client_ip(request))
    db.commit()
    db.refresh(env)
    return environment_out(env)


@router.delete("/projects/{project_id}/environments/{env_id}/variables/{key}")
def delete_variable(env_id: uuid.UUID, key: str, request: Request, project: Project = Depends(project_writer),
                    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    env = _env(db, project, env_id)
    var = db.scalar(select(EnvironmentVariable).where(EnvironmentVariable.environment_id == env.id, EnvironmentVariable.key == key))
    if var is None:
        raise HTTPException(404, "Variable not found")
    db.delete(var)
    audit.record(db, "environment.variable_deleted", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="environment", resource_id=env.id, details={"key": key}, ip_address=client_ip(request))
    db.commit()
    db.refresh(env)
    return environment_out(env)


def set_env_variable(db: Session, env: Environment, key: str, value: str, is_secret: bool) -> None:
    var = db.scalar(select(EnvironmentVariable).where(EnvironmentVariable.environment_id == env.id, EnvironmentVariable.key == key))
    if var is None:
        var = EnvironmentVariable(environment_id=env.id, key=key)
        db.add(var)
    var.is_secret = is_secret
    if is_secret:
        var.secret_ciphertext, var.value = encrypt(value), None
    else:
        var.value, var.secret_ciphertext = value, None
