from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Environment, EnvironmentVariable, Project
from ..security.crypto import decrypt


def default_environment(db: Session, project: Project) -> Optional[Environment]:
    env = db.scalar(select(Environment).where(Environment.project_id == project.id, Environment.is_default.is_(True)))
    return env or db.scalar(select(Environment).where(Environment.project_id == project.id).order_by(Environment.created_at))


def resolve_environment(db: Session, project: Project, env: Optional[Environment]) -> tuple[dict[str, str], dict[str, str], Optional[str]]:
    """Return (plain variables, decrypted secrets, base URL) for a run."""
    env = env or default_environment(db, project)
    variables: dict[str, str] = {}
    secrets: dict[str, str] = {}
    if env is not None:
        for var in db.scalars(select(EnvironmentVariable).where(EnvironmentVariable.environment_id == env.id)):
            if var.is_secret and var.secret_ciphertext:
                secrets[var.key] = decrypt(var.secret_ciphertext)
            elif var.value is not None:
                variables[var.key] = var.value
    base_url = (env.base_url if env and env.base_url else None) or project.base_url
    if base_url:
        variables.setdefault("base_url", base_url)
    return variables, secrets, base_url


def variable_names(db: Session, project: Project, env: Optional[Environment] = None) -> set[str]:
    env = env or default_environment(db, project)
    names: set[str] = set()
    if env is not None:
        names = set(db.scalars(select(EnvironmentVariable.key).where(EnvironmentVariable.environment_id == env.id)))
    if (env and env.base_url) or project.base_url:
        names.add("base_url")
    return names
