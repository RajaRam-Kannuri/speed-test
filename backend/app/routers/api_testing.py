"""Test My APIs: import OpenAPI / Swagger / Postman / manual requests, generate tests."""

from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, client_ip, get_principal, load_project, project_reader, project_writer
from ..models import AIGenerationJob, ApiCollection, ApiEndpoint, Project
from ..security.ssrf import TargetNotAllowed, check_url
from ..services import audit
from ..services.environments import default_environment
from ..services.openapi import ParsedEndpoint, ParsedSpec, SpecError, parse_spec
from ..services.testcases import create_test_case
from ..worker import enqueue, run_generation_task
from .projects import set_env_variable
from .serializers import collection_out, job_out, test_case_out

router = APIRouter(tags=["api testing"])
MAX_SPEC_BYTES = 5_000_000


class ImportIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    spec_text: Optional[str] = Field(default=None, max_length=MAX_SPEC_BYTES)
    spec_url: Optional[str] = Field(default=None, max_length=2000)
    base_url: Optional[str] = Field(default=None, max_length=2000, description="Overrides the server URL in the spec")
    api_token: Optional[str] = Field(default=None, max_length=2000, description="Stored as the secret variable api_token")
    api_key: Optional[str] = Field(default=None, max_length=2000, description="Stored as the secret variable api_key")


class ManualIn(BaseModel):
    name: str = Field(default="Manual requests", max_length=200)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str = Field(min_length=8, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Optional[Any] = None
    expected_status: list[int] = Field(default_factory=lambda: [200])
    title: Optional[str] = Field(default=None, max_length=300)


class GenerateIn(BaseModel):
    endpoint_ids: list[uuid.UUID] = Field(default_factory=list)
    use_ai: bool = True


def _store_collection(db: Session, project: Project, spec: ParsedSpec, name: Optional[str], source_url: Optional[str],
                      base_url: Optional[str], raw: Optional[str]) -> ApiCollection:
    coll = ApiCollection(project_id=project.id, name=(name or spec.title or "API")[:200], source_type=spec.source_type,
                         source_url=source_url, base_url=(base_url or spec.base_url or "").rstrip("/") or None,
                         spec_version=spec.version, raw_spec=raw, security_schemes=spec.security_schemes)
    db.add(coll)
    db.flush()
    for ep in spec.endpoints:
        db.add(ApiEndpoint(collection_id=coll.id, method=ep.method, path=ep.path, operation_id=ep.operation_id,
                           summary=(ep.summary or "")[:500], tags=ep.tags, parameters=ep.parameters,
                           request_schema=ep.request_schema, request_example=ep.request_example,
                           responses=ep.responses, security=ep.security))
    return coll


@router.post("/projects/{project_id}/api-collections", status_code=201)
def import_spec(body: ImportIn, request: Request, project: Project = Depends(project_writer),
                principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not body.spec_text and not body.spec_url:
        raise HTTPException(422, "Paste or upload a specification, or give its URL")
    text = body.spec_text
    if body.spec_url and not text:
        try:
            check_url(body.spec_url)
        except TargetNotAllowed as exc:
            raise HTTPException(422, f"This address cannot be fetched: {exc}")
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                resp = client.get(body.spec_url, headers={"accept": "application/json, application/yaml, text/yaml, */*"})
        except httpx.HTTPError as exc:
            raise HTTPException(422, f"Could not download the specification: {exc}")
        if resp.status_code != 200:
            raise HTTPException(422, f"Downloading the specification returned HTTP {resp.status_code}")
        if len(resp.content) > MAX_SPEC_BYTES:
            raise HTTPException(413, "The specification is larger than 5 MB")
        text = resp.text
    base_url = body.base_url.strip().rstrip("/") if body.base_url else None
    try:
        spec = parse_spec(text or "", body.spec_url)
    except SpecError as exc:
        raise HTTPException(422, str(exc))
    target = base_url or spec.base_url
    if not target:
        raise HTTPException(422, "The specification has no server URL. Enter the API base URL.")
    try:
        check_url(target)
    except TargetNotAllowed as exc:
        raise HTTPException(422, f"The API base URL cannot be tested: {exc}")
    coll = _store_collection(db, project, spec, body.name, body.spec_url, base_url, text)
    env = default_environment(db, project)
    if env is not None:
        set_env_variable(db, env, "api_base_url", coll.base_url, False)
        if body.api_token:
            set_env_variable(db, env, "api_token", body.api_token, True)
        if body.api_key:
            set_env_variable(db, env, "api_key", body.api_key, True)
    audit.record(db, "api_collection.imported", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="api_collection", resource_id=coll.id,
                 details={"source": spec.source_type, "endpoints": len(spec.endpoints), "base_url": coll.base_url},
                 ip_address=client_ip(request))
    db.commit()
    db.refresh(coll)
    return collection_out(coll, with_endpoints=True)


@router.post("/projects/{project_id}/api-requests", status_code=201)
def manual_request(body: ManualIn, request: Request, project: Project = Depends(project_writer),
                   principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Create a single API test from a manually entered request."""
    try:
        check_url(body.url)
    except TargetNotAllowed as exc:
        raise HTTPException(422, f"This address cannot be tested: {exc}")
    opts: dict[str, Any] = {"method": body.method, "url": body.url, "expect": {"status": body.expected_status}}
    if body.headers:
        opts["headers"] = body.headers
    if body.body is not None:
        opts["body"] = body.body
    case = create_test_case(db, project, title=body.title or f"{body.method} {body.url}", kind="api", category="functional",
                            status="draft", source="manual", expectation_basis="specified",
                            steps=[{"action": "api_request", "options": opts, "description": f"{body.method} {body.url}"}],
                            created_by=principal.user_id)
    audit.record(db, "test_case.created", organization_id=project.organization_id, project_id=project.id, user_id=principal.user_id,
                 resource_type="test_case", resource_id=case.id, ip_address=client_ip(request))
    db.commit()
    return test_case_out(db, case)


@router.get("/projects/{project_id}/api-collections")
def list_collections(project: Project = Depends(project_reader), db: Session = Depends(get_db)):
    return [collection_out(c) for c in db.scalars(select(ApiCollection).where(ApiCollection.project_id == project.id)
                                                  .order_by(ApiCollection.created_at.desc()))]


def _collection(db: Session, principal: Principal, cid: uuid.UUID, minimum: str = "viewer") -> tuple[ApiCollection, Project]:
    coll = db.get(ApiCollection, cid)
    if coll is None:
        raise HTTPException(404, "API collection not found")
    return coll, load_project(db, principal, coll.project_id, minimum)


@router.get("/api-collections/{collection_id}")
def get_collection(collection_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    coll, _ = _collection(db, principal, collection_id)
    return collection_out(coll, with_endpoints=True)


@router.delete("/api-collections/{collection_id}", status_code=204)
def delete_collection(collection_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    coll, project = _collection(db, principal, collection_id, "member")
    audit.record(db, "api_collection.deleted", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="api_collection", resource_id=coll.id)
    db.delete(coll)
    db.commit()


@router.post("/api-collections/{collection_id}/generate", status_code=202)
def generate(collection_id: uuid.UUID, body: GenerateIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    coll, project = _collection(db, principal, collection_id, "member")
    job = AIGenerationJob(project_id=project.id, kind="api_plan", source_ref=str(coll.id), engine="deterministic",
                          created_by=principal.user_id,
                          result_summary={"request": {"endpoint_ids": [str(i) for i in body.endpoint_ids], "use_ai": body.use_ai}})
    db.add(job)
    audit.record(db, "generation.requested", organization_id=project.organization_id, project_id=project.id,
                 user_id=principal.user_id, resource_type="api_collection", resource_id=coll.id)
    db.commit()
    enqueue(run_generation_task, str(job.id))
    db.refresh(job)
    return job_out(job)
