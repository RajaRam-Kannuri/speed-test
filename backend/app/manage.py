"""Administrator commands for a self-hosted install.

    python -m app.manage reset-password EMAIL             # prompts for the new password
    python -m app.manage reset-password EMAIL --generate  # prints a random one

In Docker:  docker compose exec api python -m app.manage reset-password you@example.com

Resetting a password signs the user out everywhere and is written to the audit log
of every organization the user belongs to.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from .db import SessionLocal
from .models import Membership, User, UserSession
from .security.passwords import hash_password, password_problem
from .services import audit


def reset_password(email: str, password: str) -> int:
    """Set a new password and end the user's sessions. Returns the number of sessions ended."""
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise LookupError(f"No account uses the email {email}.")
        user.password_hash = hash_password(password)
        ended = db.execute(delete(UserSession).where(UserSession.user_id == user.id)).rowcount or 0
        org_ids = list(db.scalars(select(Membership.organization_id).where(Membership.user_id == user.id))) or [None]
        for org_id in org_ids:
            audit.record(db, "user.password_reset", organization_id=org_id, user_id=user.id, resource_type="user",
                         resource_id=user.id, details={"by": "admin command", "sessions_ended": ended})
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description="LorvenLax administrator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("reset-password", help="Set a new password for a user")
    rp.add_argument("email")
    rp.add_argument("--generate", action="store_true", help="Generate a random password and print it")
    args = parser.parse_args(argv)

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
    except OperationalError as exc:
        print(f"Could not reach the database ({str(exc.orig).strip()}). Check that the stack is running: docker compose ps",
              file=sys.stderr)
        return 1
    print(f"Password updated for {args.email.strip().lower()}. Signed out of {ended} session(s).")
    if args.generate:
        print(f"New password: {password}")
    print("Sign in with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
