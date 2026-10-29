"""Administrator commands for a self-hosted install.

    python -m app.manage reset-password EMAIL             # prompts for the new password
    python -m app.manage reset-password EMAIL --generate  # prints a random one
    python -m app.manage send-test-email EMAIL            # checks the SMTP settings

In Docker:  docker compose exec api python -m app.manage <command> ...

Users normally reset their own password with the "Forgot password?" link (when email is
configured), or an admin sends them a link from Settings > Team. This command is the
last resort, for example when the only owner is locked out and email is not set up.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from .config import get_settings
from .db import SessionLocal
from .models import User
from .security.passwords import password_problem
from .services import mail, password_reset


def reset_password(email: str, password: str) -> int:
    """Set a new password and end the user's sessions. Returns the number of sessions ended."""
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise LookupError(f"No account uses the email {email}.")
        ended = password_reset.set_password(db, user, password, via="admin_command")
        db.commit()
        return ended


def _ask_password() -> str:
    while True:
        first = getpass.getpass("New password: ")
        problem = password_problem(first)
        if problem:
            print(problem, file=sys.stderr)
            continue
        if getpass.getpass("New password again: ") != first:
            print("The passwords do not match. Try again.", file=sys.stderr)
            continue
        return first


def _reset(args: argparse.Namespace) -> int:
    if args.generate:
        password = secrets.token_urlsafe(12) + str(secrets.randbelow(10))
    elif sys.stdin.isatty():
        password = _ask_password()
    else:
        print("No terminal to type a password into. Use 'docker compose exec' (not 'run -T'), or add --generate.",
              file=sys.stderr)
        return 2
    try:
        ended = reset_password(args.email, password)
    except (LookupError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Password updated for {args.email.strip().lower()}. Signed out of {ended} session(s).")
    if args.generate:
        print(f"New password: {password}")
    print("Sign in with the new password.")
    return 0


def _test_email(args: argparse.Namespace) -> int:
    s = get_settings()
    if not s.mail_enabled:
        print("Email is not configured. Set LLX_SMTP_HOST (and usually LLX_SMTP_USERNAME, LLX_SMTP_PASSWORD, "
              "LLX_MAIL_FROM) in .env, then run: docker compose up -d", file=sys.stderr)
        return 1
    print(f"Sending through {s.smtp_host}:{s.smtp_port} ({s.smtp_security}) from {s.mail_from} ...")
    if not mail.send(args.email, *mail.test_message()):
        print("Sending failed. The reason is in the log above; check the host, port, security mode and credentials.",
              file=sys.stderr)
        return 1
    print(f"Sent. Check the inbox (and spam folder) of {args.email}. Links in emails will point to {s.app_url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description="LorvenLax administrator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("reset-password", help="Set a new password for a user")
    rp.add_argument("email")
    rp.add_argument("--generate", action="store_true", help="Generate a random password and print it")
    te = sub.add_parser("send-test-email", help="Send a test email to check the SMTP settings")
    te.add_argument("email")
    args = parser.parse_args(argv)
    try:
        return _reset(args) if args.command == "reset-password" else _test_email(args)
    except OperationalError as exc:
        print(f"Could not reach the database ({str(exc.orig).strip()}). Check that the stack is running: docker compose ps",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
