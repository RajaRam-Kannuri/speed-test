"""Test configuration: a dedicated PostgreSQL database migrated with Alembic,
Celery in eager mode (jobs run inline), and the Acme CRM sample app."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEST_DB = os.environ.get("LLX_TEST_DATABASE_URL", "postgresql+psycopg://lorvenlax:lorvenlax@localhost:5432/lorvenlax_test")
SAMPLE_PORT = int(os.environ.get("LLX_TEST_SAMPLE_PORT", "8101"))

os.environ.update({
    "LLX_DATABASE_URL": TEST_DB,
    "LLX_CELERY_EAGER": "true",
    "LLX_ALLOWED_PRIVATE_HOSTS": "127.0.0.1",
    "LLX_STORAGE_LOCAL_ROOT": tempfile.mkdtemp(prefix="llx-artifacts-"),
    "LLX_ANTHROPIC_API_KEY": "",
    "LLX_RATE_LIMIT_AUTH_PER_MINUTE": "10000",
    "LLX_RATE_LIMIT_JOBS_PER_MINUTE": "10000",
    "LLX_REDIS_URL": os.environ.get("LLX_TEST_REDIS_URL", "redis://localhost:6379/15"),
})
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
sys.path.insert(0, str(ROOT / "backend"))


def _recreate_database() -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(TEST_DB)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _recreate_database()
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def sample_app():
    """Run the Acme CRM sample application on a free local port."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--port", str(SAMPLE_PORT), "--log-level", "warning"],
        cwd=ROOT / "sample-app", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", SAMPLE_PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("sample app did not start")
    yield f"http://127.0.0.1:{SAMPLE_PORT}"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class Api:
    """Small helper around TestClient that sends the CSRF header."""

    def __init__(self, client):
        self.c = client

    def _headers(self):
        return {"x-csrf-token": self.c.cookies.get("llx_csrf", "")}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers={**self._headers(), **kw.pop("headers", {})}, **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self._headers(), **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self._headers(), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._headers(), **kw)


_counter = {"n": 0}


def register(client, org: str = "Org"):
    _counter["n"] += 1
    email = f"user{_counter['n']}-{int(time.time() * 1000)}@example.com"
    r = client.post("/api/auth/register", json={"name": "Tester", "email": email, "password": "Sup3rSecret!42", "organization_name": org})
    assert r.status_code == 201, r.text
    data = r.json()
    return Api(client), data["organizations"][0]["id"], email


@pytest.fixture
def api(client):
    a, org_id, email = register(client)
    a.org_id, a.email = org_id, email
    return a


def make_project(api: Api, name: str = "Project", base_url: str | None = None) -> dict:
    r = api.post(f"/api/organizations/{api.org_id}/projects", json={"name": name, "base_url": base_url})
    assert r.status_code == 201, r.text
    return r.json()
