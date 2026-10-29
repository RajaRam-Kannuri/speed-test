from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import CSRF_COOKIE, SESSION_COOKIE, Principal, client_ip, get_principal, require_user
from ..models import Membership, Organization, User, UserSession
from ..security.passwords import hash_password, new_token, password_problem, token_hash, verify_password
from ..services import audit, mail, password_reset, ratelimit
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
    problem = password_problem(password)
    if problem:
        raise HTTPException(422, problem)


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


# --------------------------------------------------------------------------- password reset

GENERIC_RESET_MESSAGE = "If an account exists for that email, we have sent a link to reset its password."


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ResetConfirmIn(ResetTokenIn):
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


@router.get("/auth/password-reset/options")
def reset_options():
    return {"email_enabled": mail.enabled()}


@router.post("/auth/password-reset/request", status_code=202)
def request_reset(body: ResetRequestIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Email a reset link. The response is identical whether or not the account exists."""
    ip = client_ip(request)
    ratelimit.hit(f"auth:{ip}", get_settings().rate_limit_auth_per_minute)
    if not mail.enabled():
        raise HTTPException(503, "Email is not set up for this workspace. Ask your administrator to send you a reset link.")
    email = body.email.lower()
    try:
        ratelimit.hit(f"pwreset-email:{email}", 3, window_seconds=900)
    except HTTPException:
        return {"message": GENERIC_RESET_MESSAGE}  # quietly drop floods aimed at one inbox
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.is_active:
        minutes = get_settings().password_reset_minutes
        raw = password_reset.issue(db, user, "self", timedelta(minutes=minutes), ip_address=ip)
        audit.record(db, "user.password_reset_requested", user_id=user.id, resource_type="user", resource_id=user.id, ip_address=ip)
        db.commit()
        background.add_task(mail.send, user.email, *mail.password_reset(user.name, password_reset.reset_url(raw), minutes))
    return {"message": GENERIC_RESET_MESSAGE}


@router.post("/auth/password-reset/check")
def check_reset(body: ResetTokenIn, request: Request, db: Session = Depends(get_db)):
    ratelimit.hit(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    found = password_reset.find_valid(db, body.token)
    if found is None:
        raise HTTPException(400, "This link is invalid or has expired.")
    tok, user = found
    return {"email": user.email, "name": user.name, "expires_at": tok.expires_at.isoformat()}


@router.post("/auth/password-reset/confirm", status_code=204)
def confirm_reset(body: ResetConfirmIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    ip = client_ip(request)
    ratelimit.hit(f"auth:{ip}", get_settings().rate_limit_auth_per_minute)
    found = password_reset.find_valid(db, body.token, lock=True)
    if found is None:
        raise HTTPException(400, "This link is invalid or has expired.")
    tok, user = found
    try:
        password_reset.set_password(db, user, body.password, via=f"reset_link:{tok.purpose}", ip_address=ip, background=background)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return Response(status_code=204)


@router.post("/auth/change-password", status_code=204)
def change_password(body: ChangePasswordIn, request: Request, background: BackgroundTasks,
                    principal: Principal = Depends(require_user), db: Session = Depends(get_db)):
    ip = client_ip(request)
    ratelimit.hit(f"auth:{ip}", get_settings().rate_limit_auth_per_minute)
    user = principal.user
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is incorrect.")
    if body.new_password == body.current_password:
        raise HTTPException(422, "Choose a password that is different from your current one.")
    current = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(request.cookies.get(SESSION_COOKIE, ""))))
    try:
        password_reset.set_password(db, user, body.new_password, via="account_settings", ip_address=ip,
                                    keep_session_id=current.id if current else None, background=background)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return Response(status_code=204)
