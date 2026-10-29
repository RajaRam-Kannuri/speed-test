"""Password reset links and password changes.

Links are single use, short lived, stored only as SHA-256 hashes, and issuing a new link
cancels any earlier unused one. Every password change ends the user's other sessions,
is written to the audit log of each organization the user belongs to, and (when email is
configured) is confirmed to the user by email.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Membership, PasswordResetToken, User, UserSession
from ..security.passwords import hash_password, new_token, password_problem, token_hash
from . import audit, mail


def reset_url(raw: str) -> str:
    return f"{get_settings().app_url}/reset-password?token={raw}"


def issue(db: Session, user: User, purpose: str, ttl: timedelta, created_by: Optional[uuid.UUID] = None,
          ip_address: Optional[str] = None) -> str:
    """Create a reset link for ``user`` and cancel earlier unused ones. Returns the raw token."""
    now = datetime.now(timezone.utc)
    db.execute(update(PasswordResetToken)
               .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
               .values(used_at=now))
    raw = new_token()
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash(raw), purpose=purpose, created_by=created_by,
                              expires_at=now + ttl, ip_address=ip_address))
    return raw


def find_valid(db: Session, raw: str, lock: bool = False) -> Optional[tuple[PasswordResetToken, User]]:
    if not raw or len(raw) > 200:
        return None
    q = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash(raw))
    if lock:
        q = q.with_for_update()
    tok = db.scalar(q)
    if tok is None or tok.used_at is not None or tok.expires_at < datetime.now(timezone.utc):
        return None
    user = db.get(User, tok.user_id)
    if user is None or not user.is_active:
        return None
    return tok, user


def set_password(db: Session, user: User, password: str, *, via: str, actor_id: Optional[uuid.UUID] = None,
                 keep_session_id: Optional[uuid.UUID] = None, ip_address: Optional[str] = None,
                 background: Optional[BackgroundTasks] = None) -> int:
    """Validate and store a new password, end other sessions, audit, and notify. Returns sessions ended.

    Raises ValueError with a user-facing message if the password is not acceptable.
    """
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    now = datetime.now(timezone.utc)
    user.password_hash = hash_password(password)
    q = delete(UserSession).where(UserSession.user_id == user.id)
    if keep_session_id is not None:
        q = q.where(UserSession.id != keep_session_id)
    ended = db.execute(q).rowcount or 0
    db.execute(update(PasswordResetToken)
               .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
               .values(used_at=now))
    org_ids = list(db.scalars(select(Membership.organization_id).where(Membership.user_id == user.id))) or [None]
    for org_id in org_ids:
        audit.record(db, "user.password_changed", organization_id=org_id, user_id=actor_id or user.id, resource_type="user",
                     resource_id=user.id, details={"via": via, "sessions_ended": ended}, ip_address=ip_address)
    if mail.enabled():
        when = now.strftime("%d %b %Y at %H:%M UTC")
        message = mail.password_changed(user.name, when, f"{get_settings().app_url}/login")
        if background is not None:
            background.add_task(mail.send, user.email, *message)
        else:
            mail.send(user.email, *message)
    return ended
