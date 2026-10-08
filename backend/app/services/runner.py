"""Test Execution Agent: runs queued executions with the Playwright engine.

Only invoked from the Celery worker, never inside an HTTP request handler.
"""

from __future__ import annotations

import base64
import re
import json
import logging
import os
import resource
import shutil
import signal
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    Environment,
    Project,
    TestArtifact,
    TestCase,
    TestExecution,
    TestResult,
    utcnow,
)
from ..security.redaction import redact, redact_obj
from .codegen import generate_spec
from .environments import resolve_environment
from .storage import get_storage

log = logging.getLogger("lorvenlax.runner")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
KIND_BY_TYPE = {"image/png": "screenshot", "image/jpeg": "screenshot", "video/webm": "video", "application/zip": "trace"}


def _limit_resources() -> None:  # runs in the child process before exec
    os.setsid()
    resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 4096))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _config_js(execution: TestExecution) -> str:
    cfg = {
        "testDir": "tests",
        "outputDir": "artifacts",
        "timeout": execution.timeout_ms,
        "expect": {"timeout": min(10_000, execution.timeout_ms)},
        "retries": execution.retries,
        "workers": max(1, min(execution.workers, get_settings().max_parallel_workers)),
        "fullyParallel": execution.workers > 1,
        "reporter": [["json", {"outputFile": "report.json"}], ["line"]],
        "use": {
            "browserName": execution.browser,
            "headless": execution.headless,
            "screenshot": execution.capture_screenshot,
            "video": execution.capture_video,
            "trace": execution.capture_trace,
            "actionTimeout": min(15_000, execution.timeout_ms),
            "navigationTimeout": min(30_000, execution.timeout_ms),
            "ignoreHTTPSErrors": False,
            "acceptDownloads": False,
        },
    }
    return "module.exports = " + json.dumps(cfg, indent=2) + ";\n"


def _flatten_tests(suite: dict, file: Optional[str] = None) -> list[tuple[str, dict, dict]]:
    out = []
    file = suite.get("file") or file
    for spec in suite.get("specs", []):
        for test in spec.get("tests", []):
            out.append((spec.get("file") or file or "", spec, test))
    for child in suite.get("suites", []):
        out.extend(_flatten_tests(child, file))
    return out


def _step_results(result: dict, secrets: list[str]) -> list[dict]:
    steps = []
    for step in result.get("steps", []):
        title = step.get("title", "")
        if not title.startswith("Step "):
            continue
        err = step.get("error") or {}
        steps.append({
            "title": redact(title, secrets),
            "duration_ms": step.get("duration", 0),
            "status": "failed" if err else "passed",
            "error": redact(ANSI_RE.sub("", err.get("message") or "")[:2000], secrets) if err else None,
        })
    # Steps after the failing one never ran.
    failed_at = next((i for i, s in enumerate(steps) if s["status"] == "failed"), None)
    return steps if failed_at is None else steps[: failed_at + 1]


def _claim(db: Session, execution_id: uuid.UUID) -> bool:
    """Move queued -> running atomically so a redelivered task cannot run twice."""
    res = db.execute(
        update(TestExecution)
        .where(TestExecution.id == execution_id, TestExecution.status == "queued")
        .values(status="running", started_at=utcnow())
    )
    db.commit()
    return res.rowcount == 1


def run_execution(execution_id: uuid.UUID) -> str:
    settings = get_settings()
    db = SessionLocal()
    work: Optional[Path] = None
    try:
        if not _claim(db, execution_id):
            log.info("execution %s is not queued; skipping", execution_id)
            return "skipped"
        execution = db.get(TestExecution, execution_id)
        project = db.get(Project, execution.project_id)
        env = db.get(Environment, execution.environment_id) if execution.environment_id else None
        variables, secrets, base_url = resolve_environment(db, project, env)

        results = list(db.scalars(select(TestResult).where(TestResult.execution_id == execution.id)))
        settings.runs_dir.mkdir(parents=True, exist_ok=True)
        work = settings.runs_dir / str(execution.id)
        shutil.rmtree(work, ignore_errors=True)
        (work / "tests").mkdir(parents=True)
        runtime = (settings.engine_dir / "src" / "runtime").as_posix()

        file_to_result: dict[str, TestResult] = {}
        for r in results:
            case = db.get(TestCase, r.test_case_id) if r.test_case_id else None
            if case is None:
                r.status, r.error_message = "error", "Test case was deleted before the run started"
                continue
            code = generate_spec(str(case.id)[:8], case.title, list(case.steps), runtime)
            name = f"{r.id}.spec.ts"
            (work / "tests" / name).write_text(code)
            r.generated_code = code
            r.status = "running"
            r.started_at = utcnow()
            file_to_result[name] = r
        (work / "playwright.config.js").write_text(_config_js(execution))
        db.commit()

        child_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(work),
            "LLX_VARS": json.dumps({**variables, **secrets}),
            "LLX_BASE_URL": base_url or "",
            "LLX_ALLOWED_HOSTS": ",".join(sorted(settings.allowed_private_host_set)),
            "NODE_OPTIONS": "--max-old-space-size=1024",
            "CI": "1",
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
        }
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            child_env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ["PLAYWRIGHT_BROWSERS_PATH"]

        cli = settings.engine_dir / "node_modules" / "@playwright" / "test" / "cli.js"
        log_path = work / "run.log"
        started = time.monotonic()
        cancelled = timed_out = False
        with log_path.open("wb") as log_file:
            proc = subprocess.Popen(
                [settings.node_binary, str(cli), "test", "-c", str(work / "playwright.config.js")],
                cwd=work, env=child_env, stdout=log_file, stderr=subprocess.STDOUT, preexec_fn=_limit_resources,
            )
            while proc.poll() is None:
                time.sleep(1)
                if time.monotonic() - started > settings.max_run_seconds:
                    timed_out = True
                elif db.scalar(select(TestExecution.status).where(TestExecution.id == execution.id)) == "cancelling":
                    cancelled = True
                db.expire_all()
                if timed_out or cancelled:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                    break
        run_log = redact(log_path.read_text(errors="replace")[-20_000:], secrets.values())
        execution = db.get(TestExecution, execution.id)

        report_path = work / "report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        seen: set[str] = set()
        for file, spec, test in [t for s in report.get("suites", []) for t in _flatten_tests(s)]:
            name = Path(file).name
            r = file_to_result.get(name)
            if r is None:
                continue
            seen.add(name)
            _apply_test_result(db, execution, project, r, test, list(secrets.values()), work)

        for name, r in file_to_result.items():
            if name in seen:
                continue
            r.status = "cancelled" if cancelled else "error"
            r.error_message = (
                "Execution was cancelled" if cancelled
                else f"Execution exceeded {settings.max_run_seconds}s and was stopped" if timed_out
                else "The test did not run. See the run log for details."
            )
            r.log = run_log[-5000:]
            r.finished_at = utcnow()

        db.commit()
        _finish(db, execution, results, cancelled, timed_out, run_log, report.get("errors"))
        return execution.status
    except Exception as exc:  # noqa: BLE001
        log.exception("execution %s crashed", execution_id)
        db.rollback()
        execution = db.get(TestExecution, execution_id)
        if execution is not None:
            execution.status = "error"
            execution.error_message = f"Runner error: {type(exc).__name__}: {str(exc)[:500]}"
            execution.finished_at = utcnow()
            for r in db.scalars(select(TestResult).where(TestResult.execution_id == execution_id, TestResult.status.in_(["queued", "running"]))):
                r.status, r.error_message = "error", execution.error_message
            db.commit()
        return "error"
    finally:
        db.close()
        if work is not None and not os.environ.get("LLX_KEEP_RUN_DIRS"):
            shutil.rmtree(work, ignore_errors=True)


def _apply_test_result(db: Session, execution: TestExecution, project: Project, r: TestResult,
                       test: dict, secrets: list[str], work: Path) -> None:
    attempts = test.get("results", [])
    final = attempts[-1] if attempts else {}
    outcome = test.get("status")
    r.status = {"expected": "passed", "unexpected": "failed", "flaky": "flaky", "skipped": "skipped"}.get(outcome, "error")
    r.retries_used = max(0, len(attempts) - 1)
    r.duration_ms = sum(a.get("duration", 0) for a in attempts)
    if final.get("startTime"):
        try:
            r.started_at = datetime.fromisoformat(final["startTime"].replace("Z", "+00:00"))
        except ValueError:
            pass
    r.finished_at = (r.started_at or utcnow()) + timedelta(milliseconds=final.get("duration", 0))
    err = final.get("error") or {}
    if r.status in ("failed", "error") and err:
        r.error_message = redact(ANSI_RE.sub("", err.get("message", ""))[:5000], secrets)
        r.error_stack = redact(ANSI_RE.sub("", err.get("stack") or "")[:8000], secrets)
    r.step_results = _step_results(final, secrets)
    r.failed_step_index = next((i for i, s in enumerate(r.step_results) if s["status"] == "failed"), None)
    stdout = "".join(x.get("text", "") for x in final.get("stdout", []) if isinstance(x, dict))
    stderr = "".join(x.get("text", "") for x in final.get("stderr", []) if isinstance(x, dict))
    r.log = redact((stdout + stderr)[-5000:], secrets) or None

    storage = get_storage()
    prefix = f"org/{project.organization_id}/project/{project.id}/exec/{execution.id}/{r.id}"
    failure_info: dict[str, Any] = {}
    flaky_previous_errors = [redact((a.get("error") or {}).get("message", "")[:500], secrets) for a in attempts[:-1] if a.get("error")]
    for idx, att in enumerate(final.get("attachments", [])):
        name = att.get("name", "attachment")
        ctype = att.get("contentType", "application/octet-stream")
        data: Optional[bytes] = None
        if att.get("path") and Path(att["path"]).exists():
            data = Path(att["path"]).read_bytes()
        elif att.get("body"):
            data = base64.b64decode(att["body"])
        if data is None:
            continue
        if name == "lorvenlax-failure.json":
            try:
                failure_info = redact_obj(json.loads(data), secrets)
            except ValueError:
                failure_info = {}
            data = json.dumps(failure_info).encode()
            kind = "dom"
        elif ctype.startswith("application/json") or ctype.startswith("text/"):
            data = (redact(data.decode(errors="replace"), secrets) or "").encode()
            kind = "api" if name.startswith("api ") else "log"
        else:
            kind = KIND_BY_TYPE.get(ctype, "attachment")
        ext = {"screenshot": ".png", "video": ".webm", "trace": ".zip"}.get(kind, ".json" if "json" in ctype else "")
        key = f"{prefix}/{idx:02d}-{kind}{ext}"
        size = storage.put_bytes(key, data, ctype)
        db.add(TestArtifact(project_id=project.id, execution_id=execution.id, result_id=r.id, kind=kind,
                            name=name[:300], content_type=ctype, storage_key=key, size_bytes=size))

    if r.status in ("failed", "error", "flaky"):
        from ..agents.failure_analysis import analyze_result
        from ..agents.healing import suggest_repairs

        analysis = analyze_result(db, r, failure_info, flaky_previous_errors)
        r.failure_category = analysis.category
        r.failure_confidence = analysis.confidence
        r.failure_summary = analysis.summary
        r.failure_evidence = analysis.evidence
        if analysis.category == "locator_failure":
            suggest_repairs(db, project.id, r, failure_info)


def _finish(db: Session, execution: TestExecution, results: list[TestResult], cancelled: bool, timed_out: bool,
            run_log: str, report_errors: Any) -> None:
    for r in results:
        db.refresh(r)
    execution.total = len(results)
    execution.passed = sum(1 for r in results if r.status in ("passed", "flaky"))
    execution.flaky = sum(1 for r in results if r.status == "flaky")
    execution.failed = sum(1 for r in results if r.status in ("failed", "error"))
    execution.skipped = sum(1 for r in results if r.status in ("skipped", "cancelled"))
    execution.finished_at = utcnow()
    if execution.started_at:
        execution.duration_ms = int((execution.finished_at - execution.started_at).total_seconds() * 1000)
    if cancelled:
        execution.status = "cancelled"
    elif timed_out:
        execution.status = "error"
        execution.error_message = "Execution time limit reached"
    elif execution.total and execution.failed == 0 and execution.passed > 0:
        execution.status = "passed"
    else:
        execution.status = "failed"
    if report_errors:
        msgs = "; ".join((e.get("message") or "")[:300] for e in report_errors if isinstance(e, dict))
        execution.error_message = (execution.error_message or "") + msgs
    db.commit()
    try:
        from ..agents.reporting import build_execution_reports

        build_execution_reports(db, execution.id)
    except Exception:  # noqa: BLE001
        log.exception("report generation failed for %s", execution.id)
