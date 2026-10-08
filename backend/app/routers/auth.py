from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import CSRF_COOKIE, SESSION_COOKIE, Principal, client_ip, get_principal, require_user
from ..models import Membership, Organization, User, UserSession
from ..security.passwords import hash_password, new_token, token_hash, verify_password
from ..services import audit, ratelimit
from .serializers import user_out

router = APIRouter(tags=["auth"])


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    organization_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug, n = base, 1
    while db.scalar(select(Organization.id).where(Organization.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


def start_session(db: Session, user: User, request: Request, response: Response) -> None:
    settings = get_settings()
    raw = new_token()
    db.add(UserSession(token_hash=token_hash(raw), user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours),
                       ip_address=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:300]))
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, raw, httponly=True, samesite="lax", secure=settings.cookie_secure, max_age=max_age, path="/")
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(24), httponly=False, samesite="lax", secure=settings.cookie_secure, max_age=max_age, path="/")


def _password_ok(password: str) -> None:
    if len(password) < 10 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(422, "Use at least 10 characters, including letters and numbers.")


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ratelimit.hit(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    _password_ok(body.password)
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    org = Organization(name=body.organization_name.strip(), slug=unique_slug(db, body.organization_name),
                       monthly_test_run_quota=get_settings().default_monthly_test_runs)
    db.add_all([user, org])
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
    audit.record(db, "user.registered", organization_id=org.id, user_id=user.id, resource_type="user", resource_id=user.id,
                 ip_address=client_ip(request))
    start_session(db, user, request, response)
    db.commit()
    return user_out(db, user)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ratelimit.hit(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    ratelimit.hit(f"auth-email:{body.email.lower()}", 10)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        audit.record(db, "user.login_failed", details={"email": body.email.lower()}, ip_address=client_ip(request))
        db.commit()
        raise HTTPException(401, "Email or password is incorrect.")
    start_session(db, user, request, response)
    audit.record(db, "user.login", user_id=user.id, resource_type="user", resource_id=user.id, ip_address=client_ip(request))
    db.commit()
    return user_out(db, user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(raw)))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/auth/me")
def me(principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    return user_out(db, principal.user)
