"""Test Validation Agent.

Deterministic checks that reject unreliable tests before they run:
structure, required fields, locator sanity, network policy on literal URLs,
presence of assertions, variable availability, locators seen during discovery,
and (optionally) a real compile/list pass of the generated Playwright code.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from ..config import get_settings
from ..security.ssrf import TargetNotAllowed, check_url
from ..services.codegen import generate_spec
from ..services.steps import ACTIONS, ARIA_ROLES, HTTP_METHODS, LOCATOR_STRATEGIES, UI_ACTIONS

VAR_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")
BUILTIN_VARS = {"timestamp", "random"}


@dataclass
class StepData:
    action: str
    target: Optional[dict] = None
    value: Optional[str] = None
    options: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class ValidationReport:
    messages: list[dict[str, Any]] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, step: Optional[int] = None) -> None:
        self.messages.append({"level": level, "code": code, "message": message, "step": step})

    @property
    def ok(self) -> bool:
        return not any(m["level"] == "error" for m in self.messages)

    @property
    def status(self) -> str:
        if not self.ok:
            return "invalid"
        return "warnings" if any(m["level"] == "warning" for m in self.messages) else "valid"


def _vars_in(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(VAR_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _vars_in(v)
    elif isinstance(value, list):
        for v in value:
            found |= _vars_in(v)
    return found


def _check_target(report: ValidationReport, i: int, target: Any) -> None:
    if not isinstance(target, dict):
        report.add("error", "target_missing", "This step needs an element to act on.", i)
        return
    strategy, value = target.get("strategy"), target.get("value")
    if strategy not in LOCATOR_STRATEGIES:
        report.add("error", "target_strategy", f"Unknown locator type '{strategy}'.", i)
    if not isinstance(value, str) or not value.strip():
        report.add("error", "target_value", "The element locator is empty.", i)
        return
    if strategy == "role" and value not in ARIA_ROLES:
        report.add("warning", "target_role", f"'{value}' is not a common ARIA role.", i)
    if strategy == "css":
        if re.search(r"javascript:|<script|\bexpression\(", value, re.I):
            report.add("error", "target_unsafe", "The CSS selector contains unsafe content.", i)
        if re.search(r":nth-child\(\d+\).*:nth-child\(\d+\)|^(div|span)(\s*>\s*(div|span))+", value):
            report.add("warning", "target_brittle", "This selector depends on page structure and may break easily.", i)


def _check_literal_url(report: ValidationReport, i: int, url: str) -> None:
    if not url or VAR_RE.search(url) or not re.match(r"^https?://", url, re.I):
        return
    try:
        check_url(url)
    except TargetNotAllowed as exc:
        report.add("error", "url_blocked", f"URL blocked by network policy: {exc}", i)


def validate_steps(
    steps: list[StepData],
    *,
    kind: str,
    available_vars: Iterable[str] = (),
    base_url: Optional[str] = None,
    known_locators: Optional[set[tuple[str, str]]] = None,
) -> ValidationReport:
    report = ValidationReport()
    if not steps:
        report.add("error", "no_steps", "The test has no steps.")
        return report
    available = set(available_vars) | BUILTIN_VARS
    stored: set[str] = set()
    has_assertion = False

    for i, step in enumerate(steps, start=1):
        spec = ACTIONS.get(step.action)
        if spec is None:
            report.add("error", "unknown_action", f"Unknown action '{step.action}'.", i)
            continue
        if kind == "api" and step.action in UI_ACTIONS:
            report.add("error", "ui_in_api_test", "API tests cannot contain browser steps.", i)
        if spec.target == "required":
            _check_target(report, i, step.target)
        elif step.target and spec.target == "optional":
            _check_target(report, i, step.target)
        if spec.value == "required" and step.action != "api_request" and (step.value is None or str(step.value).strip() == ""):
            report.add("error", "value_missing", f"'{spec.label}' needs a {spec.value_label.lower()}.", i)
        if step.action in ("wait_ms", "assert_count") and step.value not in (None, ""):
            if not str(step.value).strip().isdigit():
                report.add("error", "value_not_number", f"{spec.value_label} must be a whole number.", i)
            elif step.action == "wait_ms" and int(step.value) > 30_000:
                report.add("warning", "long_wait", "Fixed waits over 30 seconds are capped. Prefer 'Wait for element'.", i)
        if step.action == "wait_ms":
            report.add("info", "fixed_wait", "Fixed waits slow tests down; 'Wait for element' is more reliable.", i)
        if step.action == "navigate":
            _check_literal_url(report, i, step.value or "")
            if step.value and not re.match(r"^https?://", step.value, re.I) and not base_url and not VAR_RE.search(step.value):
                report.add("error", "relative_without_base", "Relative URL needs a base URL on the project or environment.", i)
        if step.action == "api_request":
            o = step.options or {}
            method = str(o.get("method", "")).upper()
            if method not in HTTP_METHODS:
                report.add("error", "api_method", f"Unsupported HTTP method '{o.get('method')}'.", i)
            if not o.get("url"):
                report.add("error", "api_url", "The request has no URL.", i)
            else:
                _check_literal_url(report, i, str(o["url"]))
                if not re.match(r"^https?://", str(o["url"]), re.I) and not base_url and not VAR_RE.search(str(o["url"])):
                    report.add("error", "relative_without_base", "Relative API URL needs a base URL.", i)
            exp = o.get("expect") or {}
            if exp.get("status") or exp.get("status_range") or exp.get("schema") or exp.get("json"):
                has_assertion = True
            else:
                report.add("warning", "api_no_expectation", "The request does not check the response.", i)
            if exp.get("schema") is not None and not isinstance(exp.get("schema"), dict):
                report.add("error", "api_schema", "Response schema must be a JSON object.", i)
            if "raw_body" in o and "body" in o:
                report.add("error", "api_body", "Use either a JSON body or a raw body, not both.", i)
            stored |= set((o.get("store") or {}).keys())
        if spec.assertion and step.action != "api_request":
            has_assertion = True
        if step.action == "store_text" and step.value:
            stored.add(step.value)
        if step.action == "set_variable":
            name = (step.options or {}).get("name")
            if not name:
                report.add("error", "var_name", "Give the variable a name.", i)
            else:
                stored.add(name)

        missing = {v for v in _vars_in([step.value, step.options, step.target]) if v not in available and v not in stored}
        for name in sorted(missing):
            report.add("error", "var_missing", f"Variable '{name}' is not defined in the selected environment or by an earlier step.", i)

        # Absence checks (assert_hidden) legitimately target elements that are not on the page.
        if known_locators is not None and step.action != "assert_hidden" and step.target and step.target.get("strategy") in ("label", "role", "text", "placeholder", "testid"):
            key = (step.target.get("strategy"), (step.target.get("name") or step.target.get("value") or "").strip().lower())
            if key not in known_locators:
                report.add("warning", "locator_unseen", f"The element {step.target.get('strategy')} '{key[1]}' was not seen during discovery.", i)

    if not has_assertion:
        report.add("error", "no_assertion", "The test never checks anything. Add at least one assertion step.")
    if kind == "ui" and steps[0].action not in ("navigate", "set_variable", "api_request"):
        report.add("warning", "no_initial_navigation", "UI tests usually start by opening a page.", 1)
    return report


def known_locators_from_pages(pages: Iterable[Any]) -> set[tuple[str, str]]:
    """Collect (strategy, value) pairs from discovered pages for locator verification."""
    out: set[tuple[str, str]] = set()

    def add_all(locs: list[dict]) -> None:
        for loc in locs or []:
            val = (loc.get("name") if loc.get("strategy") == "role" else loc.get("value")) or ""
            out.add((loc.get("strategy"), val.strip().lower()))
            if loc.get("strategy") == "role" and loc.get("name"):
                out.add(("text", loc["name"].strip().lower()))

    for page in pages:
        for form in page.forms or []:
            for f in form.get("fields", []):
                add_all(f.get("locators", []))
            if form.get("submit"):
                add_all(form["submit"].get("locators", []))
        for link in page.links or []:
            add_all(link.get("locators", []))
        for b in page.buttons or []:
            add_all(b.get("locators", []))
        for h in page.headings or []:
            out.add(("role", h.get("text", "").strip().lower()))
            out.add(("text", h.get("text", "").strip().lower()))
        for t in page.tables or []:
            if t.get("testid"):
                out.add(("testid", t["testid"].lower()))
            for header in t.get("headers", []):
                out.add(("role", header.strip().lower()))
                out.add(("text", header.strip().lower()))
    return out


def compile_check(title: str, steps: list[StepData], timeout: int = 60) -> tuple[bool, str]:
    """Generate the spec and ask Playwright to load and list it (catches syntax/import errors)."""
    settings = get_settings()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="validate-", dir=settings.runs_dir))
    try:
        (work / "tests").mkdir()
        runtime = (settings.engine_dir / "src" / "runtime").as_posix()
        (work / "tests" / "case.spec.ts").write_text(generate_spec(str(uuid.uuid4())[:8], title, steps, runtime))
        (work / "playwright.config.js").write_text("module.exports = { testDir: 'tests', reporter: 'list' };\n")
        cli = settings.engine_dir / "node_modules" / "@playwright" / "test" / "cli.js"
        proc = subprocess.run(
            [settings.node_binary, str(cli), "test", "--list", "-c", str(work / "playwright.config.js")],
            cwd=work, capture_output=True, text=True, timeout=timeout,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin:" + str(Path(settings.node_binary).parent), "HOME": str(work)},
        )
        output = (proc.stdout + proc.stderr).strip()
        ok = proc.returncode == 0 and "Total: 1 test" in output
        return ok, output[-2000:]
    except subprocess.TimeoutExpired:
        return False, "Compile check timed out"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def steps_from_models(steps: Iterable[Any]) -> list[StepData]:
    return [StepData(s.action, s.target, s.value, dict(s.options or {}), s.description or "") for s in steps]


def steps_from_dicts(items: Iterable[dict]) -> list[StepData]:
    return [
        StepData(
            action=str(d.get("action", "")),
            target=d.get("target"),
            value=None if d.get("value") is None else str(d.get("value")),
            options=d.get("options") or {},
            description=str(d.get("description") or ""),
        )
        for d in items
    ]


def dump_messages(report: ValidationReport) -> str:
    return json.dumps(report.messages)
