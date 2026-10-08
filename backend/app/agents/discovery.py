"""Application Discovery Agent: runs the engine crawler within the authorised scope
and stores the discovered pages, elements, forms and screenshots."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import update

from ..config import get_settings
from ..db import SessionLocal
from ..models import DiscoveredPage, Environment, Project, SiteDiscovery, TestArtifact, utcnow
from ..security.redaction import redact
from ..services.environments import resolve_environment
from ..services.storage import get_storage

log = logging.getLogger("lorvenlax.discovery")


def run_discovery(discovery_id: uuid.UUID) -> str:
    settings = get_settings()
    db = SessionLocal()
    tmp = Path(tempfile.mkdtemp(prefix="discovery-", dir=_ensure(settings.runs_dir)))
    try:
        claimed = db.execute(
            update(SiteDiscovery).where(SiteDiscovery.id == discovery_id, SiteDiscovery.status == "queued")
            .values(status="running", started_at=utcnow())
        ).rowcount
        db.commit()
        if not claimed:
            return "skipped"
        disc = db.get(SiteDiscovery, discovery_id)
        project = db.get(Project, disc.project_id)
        config: dict = {"url": disc.url, "max_pages": disc.max_pages, "max_depth": disc.max_depth, "timeout_ms": 15000}
        secrets: list[str] = []
        if disc.uses_login:
            env = db.get(Environment, disc.environment_id) if disc.environment_id else None
            variables, secret_vars, _ = resolve_environment(db, project, env)
            creds = {**variables, **secret_vars}
            if creds.get("username") and creds.get("password"):
                config["login"] = {"url": disc.login_url or disc.url, "username": creds["username"], "password": creds["password"]}
                secrets = list(secret_vars.values())
        (tmp / "config.json").write_text(json.dumps(config))
        env_vars = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp),
            "LLX_ALLOWED_HOSTS": ",".join(sorted(settings.allowed_private_host_set)),
        }
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            env_vars["PLAYWRIGHT_BROWSERS_PATH"] = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        proc = subprocess.run(
            [settings.node_binary, str(settings.engine_dir / "dist" / "discover.js"), str(tmp / "config.json"), str(tmp / "out")],
            capture_output=True, text=True, timeout=600, env=env_vars, cwd=settings.engine_dir,
        )
        out_file = tmp / "out" / "discovery.json"
        if proc.returncode != 0 or not out_file.exists():
            raise RuntimeError(redact(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "crawler failed", secrets))
        data = json.loads(out_file.read_text())
        storage = get_storage()
        for i, page in enumerate(data.get("pages", [])):
            art_id = None
            shot = tmp / "out" / page.get("screenshot", "")
            if page.get("screenshot") and shot.exists():
                key = f"org/{project.organization_id}/project/{project.id}/discovery/{disc.id}/page-{i + 1}.png"
                size = storage.put_file(key, shot, "image/png")
                art = TestArtifact(project_id=project.id, discovery_id=disc.id, kind="screenshot",
                                   name=f"{page.get('title') or page['url']}"[:300], content_type="image/png",
                                   storage_key=key, size_bytes=size)
                db.add(art)
                db.flush()
                art_id = art.id
            db.add(DiscoveredPage(
                discovery_id=disc.id, position=i, url=page["url"], title=(page.get("title") or "")[:500],
                status_code=page.get("status"), depth=page.get("depth", 0), requires_login=bool(page.get("requires_login")),
                screenshot_artifact_id=art_id, headings=page.get("headings", []), forms=page.get("forms", []),
                links=page.get("links", [])[:200], buttons=page.get("buttons", [])[:100], tables=page.get("tables", []),
                text_sample=redact(page.get("text_sample", ""), secrets) or "",
            ))
        disc.login_result = data.get("login")
        disc.skipped = (data.get("skipped") or [])[:100] + [{"url": e["url"], "reason": e["error"]} for e in data.get("errors", [])][:50]
        disc.page_count = len(data.get("pages", []))
        disc.status = "completed" if disc.page_count else "failed"
        if not disc.page_count:
            disc.error_message = "No pages could be loaded. " + "; ".join(e["error"] for e in data.get("errors", [])[:3])
        if not project.base_url:
            from urllib.parse import urlsplit

            parts = urlsplit(disc.url)
            project.base_url = f"{parts.scheme}://{parts.netloc}"
        disc.finished_at = utcnow()
        db.commit()
        return disc.status
    except Exception as exc:  # noqa: BLE001
        log.exception("discovery %s failed", discovery_id)
        db.rollback()
        disc = db.get(SiteDiscovery, discovery_id)
        if disc is not None:
            disc.status = "failed"
            disc.error_message = str(exc)[:1000]
            disc.finished_at = utcnow()
            db.commit()
        return "failed"
    finally:
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
