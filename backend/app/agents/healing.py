"""Self-Healing Agent.

When a locator fails, compare the original locator with the elements captured
from the page at the moment of failure, score alternatives, and record
suggestions. Suggestions are never applied automatically: a user must accept
one, which updates only the locator of that step (never its action, value or
assertion) and is written to the audit log.
"""

from __future__ import annotations

import difflib
import re
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import HealingSuggestion, TestCase, TestResult, TestStep

ROLE_BY_TAG = {"a": "link", "button": "button", "select": "combobox", "textarea": "textbox", "h1": "heading", "h2": "heading", "h3": "heading"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _candidate_locators(c: dict) -> list[tuple[dict, str]]:
    """Locators that would identify candidate element ``c``, best first, with the text they match on."""
    out: list[tuple[dict, str]] = []
    role = c.get("role") or ROLE_BY_TAG.get(c.get("tag", ""), "")
    if c.get("tag") == "input" and not role:
        role = {"checkbox": "checkbox", "radio": "radio", "submit": "button", "button": "button"}.get(c.get("type", ""), "textbox")
    if c.get("testid"):
        out.append(({"strategy": "testid", "value": c["testid"]}, c["testid"]))
    if c.get("label"):
        out.append(({"strategy": "label", "value": c["label"]}, c["label"]))
    name = c.get("aria_label") or c.get("text") or ""
    if role and name and len(name) <= 80:
        out.append(({"strategy": "role", "value": role, "name": name}, name))
    if c.get("placeholder"):
        out.append(({"strategy": "placeholder", "value": c["placeholder"]}, c["placeholder"]))
    if c.get("id") and re.match(r"^[A-Za-z][\w-]*$", c["id"]):
        out.append(({"strategy": "css", "value": f"#{c['id']}"}, c["id"]))
    elif c.get("name"):
        out.append(({"strategy": "css", "value": f"{c['tag']}[name=\"{c['name']}\"]"}, c["name"]))
    return out


def _expected_kind(target: dict) -> set[str]:
    if target.get("strategy") == "role":
        return {target.get("value", "")}
    if target.get("strategy") in ("label", "placeholder"):
        return {"textbox", "combobox", "checkbox", "radio", "spinbutton"}
    return set()


def rank_candidates(target: dict, candidates: list[dict], limit: int = 3) -> list[dict[str, Any]]:
    wanted = _norm(target.get("name") or target.get("value") or "")
    kinds = _expected_kind(target)
    scored: list[dict[str, Any]] = []
    for c in candidates:
        if not c.get("visible", True):
            continue
        role = c.get("role") or ROLE_BY_TAG.get(c.get("tag", ""), "")
        if c.get("tag") == "input" and not role:
            role = {"checkbox": "checkbox", "radio": "radio", "submit": "button"}.get(c.get("type", ""), "textbox")
        texts = [c.get(k, "") for k in ("text", "label", "aria_label", "placeholder", "testid", "name", "id")]
        sim = max((difflib.SequenceMatcher(None, wanted, _norm(t)).ratio() for t in texts if t), default=0.0)
        if wanted and any(wanted in _norm(t) or (_norm(t) and _norm(t) in wanted) for t in texts if t):
            sim = max(sim, 0.85)
        if kinds and role not in kinds:
            sim *= 0.6
        if sim < 0.45:
            continue
        locs = _candidate_locators(c)
        if not locs:
            continue
        loc, matched = locs[0]
        # Uniqueness at failure time: how many captured elements share this locator text.
        # Ambiguity only matters among elements of the same kind (a link and a button can share text).
        def same_role(o: dict) -> bool:
            r = o.get("role") or ROLE_BY_TAG.get(o.get("tag", ""), "")
            if o.get("tag") == "input" and not r:
                r = {"checkbox": "checkbox", "radio": "radio", "submit": "button"}.get(o.get("type", ""), "textbox")
            return r == role
        dupes = sum(1 for o in candidates if o.get("visible", True) and same_role(o)
                    and _norm(matched) in [_norm(o.get(k, "")) for k in ("text", "label", "aria_label", "placeholder", "testid")])
        unique = dupes <= 1
        conf = sim * (1.0 if unique else 0.7)
        if conf < 0.4:
            continue
        scored.append({
            "target": loc,
            "confidence": round(min(conf, 0.97), 2),
            "rationale": (
                f"Element <{c.get('tag')}> with text \"{(c.get('text') or c.get('label') or c.get('aria_label') or '')[:60]}\" "
                f"matched the original locator \"{wanted}\" with similarity {sim:.2f}; "
                + ("it was the only element of that kind with this text when the test failed." if unique else "other elements had similar text, so confidence is reduced.")
            ),
        })
    scored.sort(key=lambda s: s["confidence"], reverse=True)
    dedup: list[dict[str, Any]] = []
    for s in scored:
        if s["target"] != target and s["target"] not in [d["target"] for d in dedup]:
            dedup.append(s)
    return dedup[:limit]


def suggest_repairs(db: Session, project_id: uuid.UUID, result: TestResult, failure_info: dict) -> list[HealingSuggestion]:
    target = failure_info.get("last_target")
    candidates = failure_info.get("candidates") or []
    if not target or not candidates or result.test_case_id is None:
        return []
    case = db.get(TestCase, result.test_case_id)
    step: Optional[TestStep] = None
    if case is not None and result.failed_step_index is not None and result.failed_step_index < len(case.steps):
        step = case.steps[result.failed_step_index]
    out = []
    for s in rank_candidates(target, candidates):
        hs = HealingSuggestion(project_id=project_id, result_id=result.id, test_step_id=step.id if step else None,
                               original_target=target, suggested_target=s["target"], confidence=s["confidence"],
                               rationale=s["rationale"])
        db.add(hs)
        out.append(hs)
    return out
