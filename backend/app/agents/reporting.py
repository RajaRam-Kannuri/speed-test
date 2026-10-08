"""Reporting Agent: execution summaries, trends, flaky detection, recommendations,
and downloadable HTML / PDF / Allure reports. Uses persisted execution data only."""

from __future__ import annotations

import base64
import html
import io
import json
import logging
import subprocess
import tempfile
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Project, TestArtifact, TestCase, TestExecution, TestResult
from ..services.storage import get_storage
from .failure_analysis import CATEGORIES

log = logging.getLogger("lorvenlax.reporting")


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "-"
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms} ms"


def execution_summary(execution: TestExecution, results: list[TestResult]) -> dict[str, Any]:
    cats = Counter(r.failure_category for r in results if r.failure_category and r.status in ("failed", "error"))
    slowest = sorted((r for r in results if r.duration_ms), key=lambda r: r.duration_ms or 0, reverse=True)[:5]
    rate = round(100 * execution.passed / execution.total, 1) if execution.total else 0.0
    return {
        "pass_rate": rate,
        "failure_categories": {CATEGORIES.get(k, k): v for k, v in cats.items()},
        "slowest": [{"title": r.test_title, "duration_ms": r.duration_ms} for r in slowest],
    }


def recommendations(results: list[TestResult]) -> list[str]:
    recs: list[str] = []
    cats = Counter(r.failure_category for r in results if r.status in ("failed", "error") and r.failure_category)
    if cats.get("locator_failure"):
        recs.append(f"{cats['locator_failure']} test(s) failed because an element could not be found. Review the self-healing suggestions.")
    if cats.get("environment_failure"):
        recs.append("Some failures were caused by the environment. Check that the target is reachable before re-running.")
    if cats.get("application_defect"):
        recs.append(f"{cats['application_defect']} failure(s) look like application defects. Review the evidence and report them.")
    if cats.get("test_data_failure"):
        recs.append("Some tests are missing test data. Add the missing variables to the environment.")
    flaky = [r for r in results if r.status == "flaky"]
    if flaky:
        recs.append(f"{len(flaky)} test(s) passed only after a retry. Stabilise them before relying on them for release decisions.")
    if not recs and results and all(r.status in ("passed", "flaky") for r in results):
        recs.append("All tests passed. Consider adding negative and boundary scenarios to widen coverage.")
    return recs


def render_html(db: Session, execution: TestExecution, embed_images: bool = True) -> str:
    project = db.get(Project, execution.project_id)
    results = list(db.scalars(select(TestResult).where(TestResult.execution_id == execution.id).order_by(TestResult.test_title)))
    summary = execution_summary(execution, results)
    storage = get_storage()
    rows = []
    for r in results:
        shots = ""
        if embed_images:
            arts = db.scalars(select(TestArtifact).where(TestArtifact.result_id == r.id, TestArtifact.kind == "screenshot")).all()
            for a in arts[:2]:
                if a.size_bytes < 1_500_000:
                    data = base64.b64encode(storage.read(a.storage_key)).decode()
                    shots += f'<img alt="Screenshot of {_e(r.test_title)}" src="data:{a.content_type};base64,{data}">'
        steps = "".join(
            f'<li class="{_e(s["status"])}">{_e(s["title"])} <span class="muted">{_fmt_ms(s.get("duration_ms"))}</span>'
            + (f'<pre>{_e(s["error"][:800])}</pre>' if s.get("error") else "") + "</li>"
            for s in r.step_results or []
        )
        analysis = ""
        if r.failure_category:
            ev = r.failure_evidence or {}
            analysis = (
                f'<div class="analysis"><b>{_e(CATEGORIES.get(r.failure_category, r.failure_category))}</b> '
                f'(confidence {int((r.failure_confidence or 0) * 100)}%): {_e(r.failure_summary)}'
                + "".join(f"<div>Verified: {_e(v)}</div>" for v in ev.get("verified", []))
                + "".join(f"<div>Hypothesis: {_e(v)}</div>" for v in ev.get("hypotheses", []))
                + "</div>"
            )
        rows.append(
            f'<section class="test"><h3><span class="badge {_e(r.status)}">{_e(r.status)}</span> {_e(r.test_title)}</h3>'
            f'<p class="muted">Duration {_fmt_ms(r.duration_ms)} · retries {r.retries_used} · {_e(r.browser)}</p>'
            + (f"<pre>{_e((r.error_message or '')[:1500])}</pre>" if r.error_message else "")
            + analysis + (f"<ol>{steps}</ol>" if steps else "") + shots + "</section>"
        )
    cats = "".join(f"<li>{_e(k)}: {v}</li>" for k, v in summary["failure_categories"].items()) or "<li>None</li>"
    recs = "".join(f"<li>{_e(x)}</li>" for x in recommendations(results))
    started = execution.started_at.strftime("%Y-%m-%d %H:%M UTC") if execution.started_at else "-"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Test report {str(execution.id)[:8]}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#15171f;margin:24px;font-size:13px}}
h1{{font-size:20px;margin:0}} h2{{font-size:15px;margin:22px 0 8px}} h3{{font-size:14px;margin:0 0 4px}}
.muted{{color:#5f6577}} .grid{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}}
.tile{{border:1px solid #dfe2ea;border-radius:6px;padding:10px 14px;min-width:110px}} .tile b{{display:block;font-size:20px}}
.test{{border:1px solid #dfe2ea;border-radius:6px;padding:12px;margin:10px 0;page-break-inside:avoid}}
.badge{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
.passed{{background:#e3f5e8;color:#0f6b2a}} .failed,.error{{background:#fde6e4;color:#a51d14}} .flaky{{background:#fdf1d8;color:#8a5a00}}
.skipped,.cancelled{{background:#eceef3;color:#4a5060}}
li.failed{{color:#a51d14}} pre{{white-space:pre-wrap;background:#f6f7f9;padding:8px;border-radius:4px;font-size:11.5px}}
.analysis{{background:#f3f5ff;border-radius:4px;padding:8px;margin:6px 0}} img{{max-width:100%;border:1px solid #dfe2ea;margin-top:6px}}
</style></head><body>
<h1>LorvenLax test report</h1>
<p class="muted">Project {_e(project.name)} · Execution {_e(execution.id)} · Started {started} · Browser {_e(execution.browser)} · Status {_e(execution.status)}</p>
<div class="grid">
<div class="tile">Total<b>{execution.total}</b></div><div class="tile">Passed<b>{execution.passed}</b></div>
<div class="tile">Failed<b>{execution.failed}</b></div><div class="tile">Flaky<b>{execution.flaky}</b></div>
<div class="tile">Pass rate<b>{summary['pass_rate']}%</b></div><div class="tile">Duration<b>{_fmt_ms(execution.duration_ms)}</b></div>
</div>
<h2>Failure categories</h2><ul>{cats}</ul>
<h2>Recommendations</h2><ul>{recs}</ul>
<h2>Results</h2>{''.join(rows)}
<p class="muted">Every result in this report comes from an actual Playwright run recorded by LorvenLax. Failure categories are automated assessments with the stated confidence.</p>
</body></html>"""


def build_execution_reports(db: Session, execution_id: uuid.UUID) -> None:
    execution = db.get(TestExecution, execution_id)
    project = db.get(Project, execution.project_id)
    storage = get_storage()
    prefix = f"org/{project.organization_id}/project/{project.id}/exec/{execution.id}"
    html_doc = render_html(db, execution)
    key = f"{prefix}/report.html"
    size = storage.put_bytes(key, html_doc.encode(), "text/html")
    db.add(TestArtifact(project_id=project.id, execution_id=execution.id, kind="report", name="report.html",
                        content_type="text/html", storage_key=key, size_bytes=size))
    settings = get_settings()
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "report.html", Path(tmp) / "report.pdf"
        src.write_text(html_doc)
        try:
            proc = subprocess.run([settings.node_binary, str(settings.engine_dir / "dist" / "pdf.js"), str(src), str(out)],
                                  capture_output=True, text=True, timeout=90, cwd=settings.engine_dir)
            if proc.returncode == 0 and out.exists():
                key = f"{prefix}/report.pdf"
                size = storage.put_file(key, out, "application/pdf")
                db.add(TestArtifact(project_id=project.id, execution_id=execution.id, kind="report", name="report.pdf",
                                    content_type="application/pdf", storage_key=key, size_bytes=size))
            else:
                log.warning("PDF rendering failed: %s", proc.stderr[-500:])
        except subprocess.TimeoutExpired:
            log.warning("PDF rendering timed out")
    db.commit()


def allure_zip(db: Session, execution: TestExecution) -> bytes:
    """Allure 2 compatible result files (one <uuid>-result.json per test)."""
    buf = io.BytesIO()
    status_map = {"passed": "passed", "flaky": "passed", "failed": "failed", "error": "broken", "skipped": "skipped", "cancelled": "skipped"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in db.scalars(select(TestResult).where(TestResult.execution_id == execution.id)):
            case = db.get(TestCase, r.test_case_id) if r.test_case_id else None
            start = int((r.started_at or execution.created_at).timestamp() * 1000)
            stop = start + (r.duration_ms or 0)
            doc = {
                "uuid": str(r.id), "historyId": str(r.test_case_id or r.id), "name": r.test_title, "fullName": r.test_title,
                "status": status_map.get(r.status, "unknown"), "stage": "finished", "start": start, "stop": stop,
                "statusDetails": {"message": r.error_message or "", "trace": r.error_stack or "", "flaky": r.status == "flaky"},
                "labels": [{"name": "suite", "value": execution.browser}, {"name": "framework", "value": "playwright"}]
                + ([{"name": "tag", "value": case.category}, {"name": "severity", "value": {"high": "critical", "medium": "normal", "low": "minor"}.get(case.priority, "normal")}] if case else []),
                "steps": [{"name": s["title"], "status": "failed" if s["status"] == "failed" else "passed", "stage": "finished"} for s in r.step_results or []],
            }
            zf.writestr(f"{r.id}-result.json", json.dumps(doc, indent=2))
        zf.writestr("executor.json", json.dumps({"name": "LorvenLax", "type": "lorvenlax", "buildName": str(execution.id)}))
    return buf.getvalue()


def project_dashboard(db: Session, project_ids: list[uuid.UUID], days: int = 14) -> dict[str, Any]:
    if not project_ids:
        return {"projects": 0, "tests": 0, "executions": 0, "results": {}, "pass_rate": None, "trend": [], "recent": [],
                "failure_categories": {}, "flaky_tests": [], "critical_failures": [], "recommendations": []}
    tests = db.scalar(select(func.count(TestCase.id)).where(TestCase.project_id.in_(project_ids), TestCase.status != "archived"))
    executions = db.scalar(select(func.count(TestExecution.id)).where(TestExecution.project_id.in_(project_ids)))
    status_counts = dict(db.execute(
        select(TestResult.status, func.count(TestResult.id))
        .join(TestExecution, TestExecution.id == TestResult.execution_id)
        .where(TestExecution.project_id.in_(project_ids))
        .group_by(TestResult.status)
    ).all())
    passed = status_counts.get("passed", 0) + status_counts.get("flaky", 0)
    failed = status_counts.get("failed", 0) + status_counts.get("error", 0)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trend_rows = db.execute(
        select(TestResult.created_at, TestResult.status)
        .join(TestExecution, TestExecution.id == TestResult.execution_id)
        .where(TestExecution.project_id.in_(project_ids), TestResult.created_at >= since)
    ).all()
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0})
    for created, status in trend_rows:
        d = created.date().isoformat()
        if status in ("passed", "flaky"):
            by_day[d]["passed"] += 1
        elif status in ("failed", "error"):
            by_day[d]["failed"] += 1
    today = datetime.now(timezone.utc).date()
    trend = [{"date": (today - timedelta(days=i)).isoformat(), **by_day.get((today - timedelta(days=i)).isoformat(), {"passed": 0, "failed": 0})}
             for i in range(days - 1, -1, -1)]
    recent = db.scalars(select(TestExecution).where(TestExecution.project_id.in_(project_ids))
                        .order_by(TestExecution.created_at.desc()).limit(8)).all()
    cat_rows = db.execute(
        select(TestResult.failure_category, func.count(TestResult.id))
        .join(TestExecution, TestExecution.id == TestResult.execution_id)
        .where(TestExecution.project_id.in_(project_ids), TestResult.failure_category.is_not(None), TestResult.created_at >= since)
        .group_by(TestResult.failure_category)
    ).all()

    # Flaky: retried-to-pass, or mixed pass/fail outcomes across the last 10 runs of a test.
    hist: dict[uuid.UUID, list[str]] = defaultdict(list)
    for case_id, status in db.execute(
        select(TestResult.test_case_id, TestResult.status)
        .join(TestExecution, TestExecution.id == TestResult.execution_id)
        .where(TestExecution.project_id.in_(project_ids), TestResult.test_case_id.is_not(None),
               TestResult.status.in_(["passed", "failed", "flaky", "error"]))
        .order_by(TestResult.created_at.desc())
    ):
        if len(hist[case_id]) < 10:
            hist[case_id].append(status)
    flaky = []
    for case_id, statuses in hist.items():
        p = sum(1 for s in statuses if s in ("passed", "flaky"))
        f = len(statuses) - p
        if "flaky" in statuses or (p and f and len(statuses) >= 3):
            case = db.get(TestCase, case_id)
            if case:
                flaky.append({"test_case_id": str(case_id), "title": case.title, "runs": len(statuses), "passed": p, "failed": f})

    critical = []
    latest_by_case: dict[uuid.UUID, TestResult] = {}
    for r in db.scalars(select(TestResult).join(TestExecution, TestExecution.id == TestResult.execution_id)
                        .where(TestExecution.project_id.in_(project_ids), TestResult.test_case_id.is_not(None))
                        .order_by(TestResult.created_at.desc()).limit(500)):
        latest_by_case.setdefault(r.test_case_id, r)
    for case_id, r in latest_by_case.items():
        if r.status in ("failed", "error"):
            case = db.get(TestCase, case_id)
            if case and case.priority == "high":
                critical.append({"test_case_id": str(case_id), "title": case.title, "execution_id": str(r.execution_id),
                                 "category": CATEGORIES.get(r.failure_category or "unknown")})

    latest_results = list(latest_by_case.values())
    return {
        "projects": len(project_ids),
        "tests": tests or 0,
        "executions": executions or 0,
        "results": {"passed": passed, "failed": failed, "total": sum(status_counts.values())},
        "pass_rate": round(100 * passed / (passed + failed), 1) if passed + failed else None,
        "trend": trend,
        "recent": [{"id": str(e.id), "project_id": str(e.project_id), "status": e.status, "total": e.total, "passed": e.passed,
                    "failed": e.failed, "browser": e.browser, "created_at": e.created_at.isoformat(), "duration_ms": e.duration_ms}
                   for e in recent],
        "failure_categories": {CATEGORIES.get(k, k): v for k, v in cat_rows},
        "flaky_tests": flaky[:10],
        "critical_failures": critical[:10],
        "recommendations": recommendations(latest_results),
    }
