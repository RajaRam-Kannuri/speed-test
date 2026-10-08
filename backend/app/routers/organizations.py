from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ROLE_RANK, Principal, client_ip, get_principal, require_org_role, require_user
from ..models import (
    ApiToken,
    AuditLog,
    Invitation,
    Membership,
    Organization,
    Project,
    TestExecution,
    TestResult,
    User,
)
from ..security.passwords import new_token, token_hash
from ..services import audit
from .auth import unique_slug
from .serializers import iso

router = APIRouter(tags=["organizations"])
Role = Literal["owner", "admin", "member", "viewer"]


class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = "member"


class RoleIn(BaseModel):
    role: Role


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_id: Optional[uuid.UUID] = None
    role: Literal["member", "viewer"] = "member"


@router.post("/organizations", status_code=201)
def create_org(body: OrgIn, request: Request, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    org = Organization(name=body.name.strip(), slug=unique_slug(db, body.name))
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=principal.user.id, role="owner"))
    audit.record(db, "organization.created", organization_id=org.id, user_id=principal.user_id, resource_type="organization",
                 resource_id=org.id, ip_address=client_ip(request))
    db.commit()
    return {"id": str(org.id), "name": org.name, "slug": org.slug, "role": "owner"}


@router.get("/organizations/{org_id}")
def get_org(org_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    role = require_org_role(db, principal, org_id, "viewer")
    org = db.get(Organization, org_id)
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(
        select(func.count(TestResult.id)).join(TestExecution, TestExecution.id == TestResult.execution_id)
        .join(Project, Project.id == TestExecution.project_id)
        .where(Project.organization_id == org_id, TestResult.created_at >= month_start)
    ) or 0
    return {"id": str(org.id), "name": org.name, "slug": org.slug, "plan": org.plan, "role": role,
            "usage": {"test_runs_this_month": used, "monthly_quota": org.monthly_test_run_quota}}


@router.get("/organizations/{org_id}/members")
def members(org_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "viewer")
    rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.organization_id == org_id)).all()
    invites = db.scalars(select(Invitation).where(Invitation.organization_id == org_id, Invitation.accepted_at.is_(None),
                                                  Invitation.expires_at > datetime.now(timezone.utc))).all()
    return {
        "members": [{"id": str(m.id), "user_id": str(u.id), "name": u.name, "email": u.email, "role": m.role} for m, u in rows],
        "invitations": [{"id": str(i.id), "email": i.email, "role": i.role, "expires_at": iso(i.expires_at)} for i in invites],
    }


@router.post("/organizations/{org_id}/invitations", status_code=201)
def invite(org_id: uuid.UUID, body: InviteIn, request: Request, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    role = require_org_role(db, principal, org_id, "admin")
    if ROLE_RANK[body.role] > ROLE_RANK[role]:
        raise HTTPException(403, "You cannot invite someone with a higher role than your own")
    raw = new_token("inv_")
    inv = Invitation(organization_id=org_id, email=body.email.lower(), role=body.role, token_hash=token_hash(raw),
                     invited_by=principal.user_id, expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db.add(inv)
    audit.record(db, "member.invited", organization_id=org_id, user_id=principal.user_id, resource_type="invitation",
                 details={"email": inv.email, "role": inv.role}, ip_address=client_ip(request))
    db.commit()
    # No email service is configured: return the acceptance token so an admin can share the link.
    return {"id": str(inv.id), "email": inv.email, "role": inv.role, "accept_token": raw, "accept_path": f"/invite/{raw}"}


@router.post("/invitations/{token}/accept")
def accept(token: str, request: Request, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
    if inv is None or inv.accepted_at or inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(404, "This invitation is invalid or has expired")
    if inv.email != principal.user.email:
        raise HTTPException(403, "This invitation was sent to a different email address")
    if not db.scalar(select(Membership).where(Membership.organization_id == inv.organization_id, Membership.user_id == principal.user.id)):
        db.add(Membership(organization_id=inv.organization_id, user_id=principal.user.id, role=inv.role))
    inv.accepted_at = datetime.now(timezone.utc)
    audit.record(db, "member.joined", organization_id=inv.organization_id, user_id=principal.user_id, ip_address=client_ip(request))
    db.commit()
    return {"organization_id": str(inv.organization_id), "role": inv.role}


@router.patch("/organizations/{org_id}/members/{membership_id}")
def change_role(org_id: uuid.UUID, membership_id: uuid.UUID, body: RoleIn, request: Request,
                principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    role = require_org_role(db, principal, org_id, "admin")
    m = db.get(Membership, membership_id)
    if m is None or m.organization_id != org_id:
        raise HTTPException(404, "Member not found")
    if ROLE_RANK[body.role] > ROLE_RANK[role] or ROLE_RANK[m.role] > ROLE_RANK[role]:
        raise HTTPException(403, "You cannot change a role above your own")
    if m.role == "owner" and body.role != "owner":
        owners = db.scalar(select(func.count(Membership.id)).where(Membership.organization_id == org_id, Membership.role == "owner"))
        if owners <= 1:
            raise HTTPException(409, "An organization needs at least one owner")
    old, m.role = m.role, body.role
    audit.record(db, "member.role_changed", organization_id=org_id, user_id=principal.user_id, resource_type="membership",
                 resource_id=m.id, details={"from": old, "to": body.role}, ip_address=client_ip(request))
    db.commit()
    return {"id": str(m.id), "role": m.role}


@router.delete("/organizations/{org_id}/members/{membership_id}", status_code=204)
def remove_member(org_id: uuid.UUID, membership_id: uuid.UUID, request: Request,
                  principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    role = require_org_role(db, principal, org_id, "admin")
    m = db.get(Membership, membership_id)
    if m is None or m.organization_id != org_id:
        raise HTTPException(404, "Member not found")
    if ROLE_RANK[m.role] > ROLE_RANK[role]:
        raise HTTPException(403, "You cannot remove someone with a higher role")
    if m.role == "owner" and db.scalar(select(func.count(Membership.id)).where(Membership.organization_id == org_id, Membership.role == "owner")) <= 1:
        raise HTTPException(409, "An organization needs at least one owner")
    db.delete(m)
    audit.record(db, "member.removed", organization_id=org_id, user_id=principal.user_id, resource_type="membership",
                 resource_id=membership_id, ip_address=client_ip(request))
    db.commit()


@router.get("/organizations/{org_id}/api-tokens")
def list_tokens(org_id: uuid.UUID, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "admin")
    tokens = db.scalars(select(ApiToken).where(ApiToken.organization_id == org_id).order_by(ApiToken.created_at.desc())).all()
    return [{"id": str(t.id), "name": t.name, "prefix": t.token_prefix, "role": t.role, "project_id": str(t.project_id) if t.project_id else None,
             "created_at": iso(t.created_at), "last_used_at": iso(t.last_used_at), "revoked": t.revoked_at is not None} for t in tokens]


@router.post("/organizations/{org_id}/api-tokens", status_code=201)
def create_token(org_id: uuid.UUID, body: TokenIn, request: Request, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "admin")
    if body.project_id is not None:
        project = db.get(Project, body.project_id)
        if project is None or project.organization_id != org_id:
            raise HTTPException(404, "Project not found")
    raw = new_token("llx_")
    tok = ApiToken(organization_id=org_id, project_id=body.project_id, name=body.name, token_prefix=raw[:10],
                   token_hash=token_hash(raw), role=body.role, created_by=principal.user_id)
    db.add(tok)
    audit.record(db, "api_token.created", organization_id=org_id, user_id=principal.user_id, resource_type="api_token",
                 details={"name": body.name, "project_id": str(body.project_id) if body.project_id else None}, ip_address=client_ip(request))
    db.commit()
    return {"id": str(tok.id), "name": tok.name, "token": raw, "note": "Copy this token now. It will not be shown again."}


@router.delete("/organizations/{org_id}/api-tokens/{token_id}", status_code=204)
def revoke_token(org_id: uuid.UUID, token_id: uuid.UUID, request: Request, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "admin")
    tok = db.get(ApiToken, token_id)
    if tok is None or tok.organization_id != org_id:
        raise HTTPException(404, "Token not found")
    tok.revoked_at = datetime.now(timezone.utc)
    audit.record(db, "api_token.revoked", organization_id=org_id, user_id=principal.user_id, resource_type="api_token",
                 resource_id=token_id, ip_address=client_ip(request))
    db.commit()


@router.get("/organizations/{org_id}/audit-logs")
def audit_logs(org_id: uuid.UUID, limit: int = 100, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "admin")
    rows = db.execute(select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id)
                      .where(AuditLog.organization_id == org_id).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": str(a.id), "action": a.action, "user": email, "resource_type": a.resource_type, "resource_id": a.resource_id,
             "project_id": str(a.project_id) if a.project_id else None, "details": a.details, "ip_address": a.ip_address,
             "created_at": iso(a.created_at)} for a, email in rows]
