"""Password reset by email, admin reset links, change password, and invitation emails.

Mail goes through the real smtplib code path to a small SMTP server running in the test.
"""

from __future__ import annotations

import email
import email.policy
import re
import socketserver
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, Membership, PasswordResetToken, User

from .conftest import register

PASSWORD = "Sup3rSecret!42"


class _SmtpHandler(socketserver.StreamRequestHandler):
    def handle(self):
        def say(line: str):
            self.wfile.write((line + "\r\n").encode())

        say("220 test-smtp ready")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode(errors="replace").strip().upper()
            if cmd.startswith(("EHLO", "HELO")):
                say("250-test-smtp")
                say("250 OK")
            elif cmd == "DATA":
                say("354 end with <CRLF>.<CRLF>")
                data = b""
                while True:
                    chunk = self.rfile.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    data += chunk[1:] if chunk.startswith(b"..") else chunk
                self.server.outbox.append(email.message_from_bytes(data, policy=email.policy.default))
                say("250 queued")
            elif cmd == "QUIT":
                say("221 bye")
                return
            else:
                say("250 OK")


class Outbox(list):
    def to(self, address: str):
        return [m for m in self if m["To"] == address]

    @staticmethod
    def text(msg) -> str:
        return msg.get_body(preferencelist=("plain",)).get_content()

    def reset_token(self, address: str) -> str:
        return re.search(r"/reset-password\?token=([\w-]+)", self.text(self.to(address)[-1])).group(1)


@pytest.fixture
def outbox(monkeypatch):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SmtpHandler)
    server.daemon_threads = True
    server.outbox = Outbox()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(s, "smtp_port", server.server_address[1])
    monkeypatch.setattr(s, "smtp_security", "none")
    monkeypatch.setattr(s, "mail_from", "LorvenLax <no-reply@lorvenlax.test>")
    monkeypatch.setattr(s, "public_url", "https://app.lorvenlax.test")
    yield server.outbox
    server.shutdown()
    server.server_close()


def _audit_actions(user_email: str) -> list[str]:
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == user_email))
        return list(db.scalars(select(AuditLog.action).where(AuditLog.resource_id == str(uid))))


def test_without_email_the_request_endpoint_explains_how_to_get_a_link(client):
    assert client.get("/api/auth/password-reset/options").json() == {"email_enabled": False}
    r = client.post("/api/auth/password-reset/request", json={"email": "someone@example.com"})
    assert r.status_code == 503 and "administrator" in r.json()["detail"]


def test_reset_by_email_end_to_end(client, outbox):
    api, _, user_email = register(client)
    assert client.get("/api/auth/password-reset/options").json() == {"email_enabled": True}

    r = client.post("/api/auth/password-reset/request", json={"email": user_email.upper()})
    assert r.status_code == 202
    unknown = client.post("/api/auth/password-reset/request", json={"email": "no-such-user@example.com"})
    assert unknown.status_code == 202 and unknown.json() == r.json()  # no account enumeration
    assert len(outbox) == 1 and outbox[0]["To"] == user_email
    msg = outbox[0]
    assert msg["Subject"] == "Reset your LorvenLax password" and "no-reply@lorvenlax.test" in msg["From"]
    assert "https://app.lorvenlax.test/reset-password?token=" in Outbox.text(msg)
    assert "Choose a new password" in msg.get_body(preferencelist=("html",)).get_content()
    token = outbox.reset_token(user_email)

    assert client.post("/api/auth/password-reset/check", json={"token": token}).json()["email"] == user_email
    weak = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "short"})
    assert weak.status_code == 422
    assert client.post("/api/auth/password-reset/check", json={"token": token}).status_code == 200  # still usable

    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "Brand-New-Pass-1"}).status_code == 204
    assert api.get("/api/auth/me").status_code == 401  # every session ended
    assert client.post("/api/auth/login", json={"email": user_email, "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"email": user_email, "password": "Brand-New-Pass-1"}).status_code == 200
    again = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "Another-Pass-2"})
    assert again.status_code == 400  # single use

    changed = outbox.to(user_email)[-1]
    assert changed["Subject"] == "Your LorvenLax password was changed"
    actions = _audit_actions(user_email)
    assert "user.password_reset_requested" in actions and "user.password_changed" in actions
    with SessionLocal() as db:
        details = db.scalars(select(AuditLog.details).where(AuditLog.action == "user.password_changed")).all()
        assert all("Brand-New-Pass-1" not in str(d) for d in details)


def test_new_link_cancels_old_one_and_expired_links_fail(client, outbox):
    _, _, user_email = register(client)
    client.post("/api/auth/password-reset/request", json={"email": user_email})
    first = outbox.reset_token(user_email)
    client.post("/api/auth/password-reset/request", json={"email": user_email})
    second = outbox.reset_token(user_email)
    assert first != second
    assert client.post("/api/auth/password-reset/check", json={"token": first}).status_code == 400
    assert client.post("/api/auth/password-reset/check", json={"token": second}).status_code == 200
    with SessionLocal() as db:
        db.execute(update(PasswordResetToken).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
                   .where(PasswordResetToken.used_at.is_(None)))
        db.commit()
    r = client.post("/api/auth/password-reset/confirm", json={"token": second, "password": "Brand-New-Pass-1"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    assert client.post("/api/auth/password-reset/check", json={"token": "made-up"}).status_code == 400


def test_requests_for_one_inbox_are_capped(client, outbox):
    _, _, user_email = register(client)
    for _ in range(5):
        assert client.post("/api/auth/password-reset/request", json={"email": user_email}).status_code == 202
    assert len(outbox.to(user_email)) == 3


def _join(api, role: str, only_this_org: bool = True):
    """Add a new user to api's organization. Optionally drop their own home organization."""
    other = TestClient(app)
    member, home_org, member_email = register(other, "Home")
    inv = api.post(f"/api/organizations/{api.org_id}/invitations", json={"email": member_email, "role": role}).json()
    assert member.post(f"/api/invitations/{inv['accept_token']}/accept").status_code == 200
    with SessionLocal() as db:
        if only_this_org:
            db.execute(delete(Membership).where(Membership.organization_id == home_org))
            db.commit()
        uid = db.scalar(select(User.id).where(User.email == member_email))
        membership = db.scalar(select(Membership.id).where(Membership.user_id == uid, Membership.organization_id == api.org_id))
    return member, member_email, str(membership)


def test_admin_reset_link_without_email(client, api):
    member, member_email, mid = _join(api, "member")
    r = api.post(f"/api/organizations/{api.org_id}/members/{mid}/password-reset")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["emailed"] is False and body["expires_in_hours"] == 24
    token = body["reset_path"].split("token=")[1]
    assert client.post("/api/auth/password-reset/check", json={"token": token}).json()["email"] == member_email
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "Member-New-Pass-1"}).status_code == 204
    assert member.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": member_email, "password": "Member-New-Pass-1"}).status_code == 200
    assert "member.password_reset_link_created" in [a for a in _audit_actions(member_email)]


def test_admin_reset_rules(client, api):
    member, _, member_mid = _join(api, "member")
    admin, _, admin_mid = _join(api, "admin")
    _, _, multi_mid = _join(api, "member", only_this_org=False)
    with SessionLocal() as db:
        owner_mid = str(db.scalar(select(Membership.id).where(Membership.organization_id == api.org_id, Membership.role == "owner")))

    reset = lambda who, mid: who.post(f"/api/organizations/{api.org_id}/members/{mid}/password-reset")  # noqa: E731
    assert reset(member, admin_mid).status_code == 403  # members cannot reset anyone
    assert reset(admin, owner_mid).status_code == 403  # admins cannot reset owners
    assert reset(admin, member_mid).status_code == 201
    assert reset(api, owner_mid).status_code == 400  # own account: use change password
    r = reset(api, multi_mid)
    assert r.status_code == 409 and "Forgot password" in r.json()["detail"]

    with TestClient(app) as stranger_client:  # another tenant cannot reach this organization
        stranger, _, _ = register(stranger_client, "Elsewhere")
        assert reset(stranger, member_mid).status_code == 404


def test_admin_reset_link_is_emailed_when_email_is_set_up(client, api, outbox):
    _, member_email, mid = _join(api, "member")
    body = api.post(f"/api/organizations/{api.org_id}/members/{mid}/password-reset").json()
    assert body["emailed"] is True and "reset_path" not in body
    msg = outbox.to(member_email)[-1]
    assert msg["Subject"] == "Set a new LorvenLax password" and "an administrator" in Outbox.text(msg)
    assert client.post("/api/auth/password-reset/check", json={"token": outbox.reset_token(member_email)}).status_code == 200


def test_change_password_keeps_this_session_and_ends_others(client, api):
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"email": api.email, "password": PASSWORD}).status_code == 200
    wrong = api.post("/api/auth/change-password", json={"current_password": "nope", "new_password": "Changed-Pass-123"})
    assert wrong.status_code == 400
    same = api.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert same.status_code == 422
    weak = api.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"})
    assert weak.status_code == 422
    ok = api.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "Changed-Pass-123"})
    assert ok.status_code == 204
    assert api.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    no_csrf = client.post("/api/auth/change-password", json={"current_password": "Changed-Pass-123", "new_password": "Other-Pass-456"})
    assert no_csrf.status_code == 403


def test_invitations_are_emailed_when_email_is_set_up(api, outbox):
    r = api.post(f"/api/organizations/{api.org_id}/invitations", json={"email": "newcomer@example.com", "role": "member"})
    assert r.json()["emailed"] is True
    msg = outbox.to("newcomer@example.com")[-1]
    assert "invited you to" in msg["Subject"]
    assert f"https://app.lorvenlax.test/invite/{r.json()['accept_token']}" in Outbox.text(msg)


def test_send_test_email_command(outbox, capsys):
    from app.manage import main

    assert main(["send-test-email", "admin@example.com"]) == 0
    assert outbox.to("admin@example.com")[-1]["Subject"] == "LorvenLax email is working"
    assert "https://app.lorvenlax.test" in capsys.readouterr().out
