from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text

from ..config import get_settings
from ..db import SessionLocal

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    status = {"api": "ok"}
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
        status["database"] = "ok"
    except Exception:  # noqa: BLE001
        status["database"] = "unavailable"
    return status


@router.get("/capabilities")
def capabilities():
    """What this deployment can do. The UI uses it to label AI output honestly."""
    s = get_settings()
    browsers_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache" / "ms-playwright"))
    installed = {b: any(p.name.startswith(b) for p in browsers_root.glob("*")) if browsers_root.exists() else False
                 for b in ("chromium", "firefox", "webkit")}
    return {
        "ai": {"enabled": s.ai_enabled, "provider": "anthropic" if s.ai_enabled else "none",
               "model": s.ai_model if s.ai_enabled else None,
               "note": None if s.ai_enabled else "No AI key configured: built-in deterministic agents are used for planning and analysis."},
        "browsers": installed,
        "storage": s.storage_backend,
        "max_run_seconds": s.max_run_seconds,
    }
