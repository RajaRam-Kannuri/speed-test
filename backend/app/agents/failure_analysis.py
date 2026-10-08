"""Failure Analysis Agent.

Classifies failed results from real evidence (Playwright error, failing step,
console errors, failed requests, retry outcome, execution history). Each
analysis separates *verified* facts (read directly from the run) from
*hypotheses* (interpretations), and carries a confidence score. When an AI
provider is configured, it adds a clearly labelled explanation on top; the
deterministic classification is never replaced silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TestResult

CATEGORIES = {
    "application_defect": "Potential application defect",
    "automation_defect": "Automation defect",
    "environment_failure": "Environment failure",
    "test_data_failure": "Test data issue",
    "locator_failure": "Locator issue",
    "assertion_failure": "Assertion failure",
    "timeout": "Timeout",
    "potential_flaky": "Potential flaky test",
    "unknown": "Unknown",
}


@dataclass
class Analysis:
    category: str
    confidence: float
    summary: str
    verified: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    @property
    def evidence(self) -> dict[str, Any]:
        return {"verified": self.verified, "hypotheses": self.hypotheses, "next_actions": self.next_actions,
                "label": CATEGORIES[self.category]}


ENV_PATTERNS = re.compile(
    r"ERR_CONNECTION_REFUSED|ECONNREFUSED|ENOTFOUND|ERR_NAME_NOT_RESOLVED|could not be resolved|ERR_CONNECTION_RESET|"
    r"ERR_INTERNET_DISCONNECTED|ECONNRESET|socket hang up|ERR_SSL|certificate|Executable doesn't exist|browserType.launch",
    re.I,
)


def _history(db: Session, result: TestResult, limit: int = 10) -> list[str]:
    if result.test_case_id is None:
        return []
    rows = db.scalars(
        select(TestResult.status)
        .where(TestResult.test_case_id == result.test_case_id, TestResult.id != result.id,
               TestResult.status.in_(["passed", "failed", "flaky", "error"]))
        .order_by(TestResult.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def analyze_result(db: Session, result: TestResult, failure_info: dict | None = None,
                   previous_attempt_errors: list[str] | None = None) -> Analysis:
    info = failure_info or {}
    msg = result.error_message or ""
    low = msg.lower()
    step_no = (result.failed_step_index + 1) if result.failed_step_index is not None else None
    step_title = result.step_results[result.failed_step_index]["title"] if step_no else None
    verified: list[str] = []
    if step_title:
        verified.append(f"Failed at {step_title}")
    if msg:
        verified.append("Playwright error: " + msg.strip().splitlines()[0][:300])
    if info.get("page_url"):
        verified.append(f"Page URL at failure: {info['page_url']}")
    for e in (info.get("console_errors") or [])[:3]:
        verified.append(f"Browser console error: {e[:200]}")
    for e in (info.get("failed_requests") or [])[:3]:
        verified.append(f"Failed network request: {e[:200]}")
    history = _history(db, result)
    if history:
        verified.append(f"Previous {len(history)} runs: {sum(1 for h in history if h in ('passed', 'flaky'))} passed, "
                        f"{sum(1 for h in history if h in ('failed', 'error'))} failed")

    def make(cat: str, conf: float, summary: str, hyps: list[str], actions: list[str]) -> Analysis:
        return Analysis(cat, round(conf, 2), summary, verified, hyps, actions)

    if result.status == "flaky":
        prev = (previous_attempt_errors or [""])[0]
        verified.append(f"Failed on attempt 1 ({prev[:150]}) and passed on retry")
        return make("potential_flaky", 0.85, "The test failed and then passed on retry without any change.",
                    ["Timing or shared test data likely varies between runs."],
                    ["Replace fixed waits with 'Wait for element' steps", "Check whether tests share data that another run changes"])
    if "blocked by network policy" in low:
        return make("environment_failure", 0.95, "The target was blocked by the platform's network policy.",
                    [], ["Ask an administrator to allow this host if it is an approved internal test target"])
    if "is not defined in the environment" in msg:
        name = re.search(r'Variable "([^"]+)"', msg)
        return make("test_data_failure", 0.95, f"Test data is missing: variable {name.group(1) if name else ''} is not set.",
                    [], ["Add the variable to the environment used for this run"])
    if ENV_PATTERNS.search(msg):
        return make("environment_failure", 0.85, "The application or browser could not be reached.",
                    ["The target environment may be down, or DNS / TLS is misconfigured."],
                    ["Check that the application is running and reachable from the test workers", "Re-run once the environment is healthy"])
    if re.search(r"SyntaxError|ReferenceError|TypeError: .* is not a function|Cannot find module|Unknown locator strategy", msg):
        return make("automation_defect", 0.9, "The test code itself failed to run.",
                    ["A step has an invalid configuration."], ["Open the test, run Validate, and fix the reported step"])
    http = re.search(r"HTTP status (\d{3})", msg) or re.search(r"returned HTTP (\d{3})", msg)
    if http:
        code = int(http.group(1))
        if code >= 500:
            return make("application_defect", 0.8, f"The application returned a server error (HTTP {code}).",
                        ["A server-side error usually indicates an application defect."],
                        ["Check application logs for the request", "File a defect with the request details from the API attachment"])
        if "response does not match schema" in low:
            pass
        else:
            return make("assertion_failure", 0.6, f"The response status (HTTP {code}) did not match the expected status.",
                        ["Either the application behaves differently from its specification (possible defect), or the test expectation or test data is wrong."],
                        ["Compare the response in the API attachment with the API specification", "If the specification is right, report a defect"])
    if "response does not match schema" in low:
        return make("application_defect", 0.7, "The response body does not match the documented schema.",
                    ["The API breaks its contract, or the specification is out of date."],
                    ["Compare the schema error with the API specification and agree which one is correct"])
    if re.search(r"Test timeout of \d+ms exceeded", msg) and not re.search(r"waiting for (getBy|locator)", msg):
        return make("timeout", 0.75, "The test exceeded its time limit.",
                    ["The application may be slow, or a step is waiting for something that never happens."],
                    ["Check the trace for the slowest step", "Raise the test timeout only if the application is legitimately slow"])
    locator_wait = re.search(r"waiting for (getBy\w+\(.*?\)|locator\(.*?\))", msg, re.S)
    if locator_wait and info.get("last_action") in ("click", "fill", "select", "check", "uncheck", "wait_for", "press", "store_text"):
        return make("locator_failure", 0.8, "An element the test acts on could not be found.",
                    ["The element's label, text or structure probably changed, or the page did not reach the expected state."],
                    ["Review the self-healing suggestions for this result", "Check the screenshot to confirm the page state"])
    if "expect(" in msg or "toBeVisible" in msg or "toContainText" in msg or "toHaveURL" in msg or "toHaveTitle" in msg:
        hyps = ["The application did not reach the expected state. This may be a defect, or the expectation may be wrong."]
        if history and all(h in ("passed", "flaky") for h in history[:3]):
            hyps.append("This test passed in its last runs, so a recent application change is a likely cause.")
        if info.get("console_errors"):
            hyps.append("Browser console errors were recorded, which makes an application defect more likely.")
        return make("assertion_failure", 0.7, "An assertion failed: the page did not show what the test expected.", hyps,
                    ["Compare the screenshot with the expectation", "If the application is wrong, report a defect; if the test is wrong, update the step"])
    if locator_wait:
        return make("locator_failure", 0.6, "The test timed out waiting for an element.", [], ["Review the self-healing suggestions"])
    if history and sum(1 for h in history if h in ("passed", "flaky")) >= max(2, len(history) // 2) and "timeout" in low:
        return make("potential_flaky", 0.5, "Intermittent timeout in a test that usually passes.", [], ["Re-run to confirm"])
    return make("unknown", 0.3, "The failure could not be classified automatically.", [],
                ["Open the trace and screenshot to investigate"])
