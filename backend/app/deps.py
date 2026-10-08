"""Authentication, authorization and tenant scoping for every request.

Every project-scoped endpoint goes through ``project_access``, which loads the
project and verifies that the caller is a member of its organization with at
least the required role. Endpoints never query tenant data by id alone.
"""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiToken, Membership, Project, User, UserSession
from .security.passwords import token_hash

SESSION_COOKIE = "llx_session"
CSRF_COOKIE = "llx_csrf"
CSRF_HEADER = "x-csrf-token"
ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    user: Optional[User]
    api_token: Optional[ApiToken] = None

    @property
    def user_id(self) -> Optional[uuid.UUID]:
        return self.user.id if self.user else None

    def role_in(self, db: Session, organization_id: uuid.UUID) -> Optional[str]:
        if self.api_token is not None:
            return self.api_token.role if self.api_token.organization_id == organization_id else None
        m = db.scalar(
            select(Membership).where(Membership.organization_id == organization_id, Membership.user_id == self.user.id)
        )
        return m.role if m else None


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer llx_"):
        token = db.scalar(select(ApiToken).where(ApiToken.token_hash == token_hash(auth[7:].strip())))
        if token is None or token.revoked_at is not None:
            raise HTTPException(401, "Invalid API token")
        token.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return Principal(user=None, api_token=token)

    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(401, "Sign in to continue")
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(raw)))
    if session is None or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, "Your session has expired. Sign in again.")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Account is disabled")

    if request.method not in SAFE_METHODS:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get(CSRF_HEADER, "")
        if not cookie or not hmac.compare_digest(cookie, header):
            raise HTTPException(403, "Missing or invalid CSRF token")
    return Principal(user=user)


def require_user(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.user is None:
        raise HTTPException(403, "This endpoint requires a signed-in user")
    return principal


def require_org_role(db: Session, principal: Principal, organization_id: uuid.UUID, minimum: str) -> str:
    role = principal.role_in(db, organization_id)
    if role is None:
        # Same response as a missing org so tenants cannot probe each other.
        raise HTTPException(404, "Organization not found")
    if ROLE_RANK[role] < ROLE_RANK[minimum]:
        raise HTTPException(403, f"This action needs the {minimum} role or higher")
    return role


def load_project(db: Session, principal: Principal, project_id: uuid.UUID, minimum: str = "viewer") -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if principal.api_token is not None and principal.api_token.project_id not in (None, project.id):
        raise HTTPException(404, "Project not found")
    role = principal.role_in(db, project.organization_id)
    if role is None:
        raise HTTPException(404, "Project not found")
    if ROLE_RANK[role] < ROLE_RANK[minimum]:
        raise HTTPException(403, f"This action needs the {minimum} role or higher")
    return project


def project_reader(project_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Project:
    return load_project(db, principal, project_id, "viewer")


def project_writer(project_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Project:
    return load_project(db, principal, project_id, "member")


def project_admin(project_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Project:
    return load_project(db, principal, project_id, "admin")
