"""Test Planning + Test Generation agents for websites.

Turns discovery results into structured test scenarios. The deterministic
planner covers page smoke checks, navigation, login, mandatory fields, invalid
input, form submission, length boundaries and tables. When Claude is
configured it proposes additional scenarios, which are only kept if every
locator they use was seen during discovery.

Each scenario records the basis of its expectation:
  discovered - observed during discovery (a regression baseline)
  confirmed  - verified during discovery (e.g. a login that succeeded)
  inferred   - a reasonable assumption the user should review
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

from .llm import STEP_SCHEMA, LLMUnavailable, get_provider, untrusted
from .validation import known_locators_from_pages

log = logging.getLogger("lorvenlax.planner")


@dataclass
class PlannedTest:
    title: str
    category: str
    priority: str
    description: str
    steps: list[dict[str, Any]]
    expectation_basis: str = "inferred"
    tags: list[str] = field(default_factory=list)
    engine: str = "deterministic"


def _path(url: str) -> str:
    p = urlsplit(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _step(action: str, target: Optional[dict] = None, value: Optional[str] = None, description: str = "", **options: Any) -> dict:
    return {"action": action, "target": target, "value": value, "options": options, "description": description}


def _best(locators: list[dict]) -> Optional[dict]:
    order = {"testid": 0, "label": 1, "role": 2, "placeholder": 3, "css": 4}
    return sorted(locators, key=lambda l: order.get(l.get("strategy"), 9))[0] if locators else None


def _title_core(title: str) -> str:
    # "Sign in | Acme CRM" -> "Sign in"
    return re.split(r"\s+[|\-–—]\s+", title)[0].strip() or title


def sample_value(field: dict) -> Optional[str]:
    t, maxlen = field.get("type", "text"), int(field.get("maxlength") or 0) or None
    minlen = int(field.get("minlength") or 0)
    if t == "email":
        return "qa.{{timestamp}}@example.com"
    if t == "password":
        return "Test-{{random}}-9"
    if t == "number":
        lo = float(field.get("min") or 1)
        hi = float(field.get("max") or lo + 10)
        return str(int((lo + hi) // 2))
    if t == "tel":
        return "5550100"
    if t == "url":
        return "https://example.com"
    if t == "date":
        return "2025-01-15"
    if t in ("checkbox", "radio", "select", "hidden", "file"):
        return None
    if t == "textarea":
        text = "Automated test message created by LorvenLax."
        if minlen > len(text):
            text = text + " x" * ((minlen - len(text)) // 2 + 1)
        return text[:maxlen] if maxlen else text
    text = "LorvenLax {{timestamp}}"
    if maxlen and maxlen < 23:
        text = "QA{{random}}"[: maxlen + 8] if maxlen >= 10 else "Q" * max(minlen, 1)
    return text


def _fill_form_steps(form: dict, skip: Optional[str] = None, override: Optional[dict] = None) -> list[dict]:
    steps = []
    override = override or {}
    for f in form.get("fields", []):
        loc = _best(f.get("locators", []))
        if not loc or f.get("name") == skip:
            continue
        label = f.get("label") or f.get("name") or "field"
        if f["type"] == "select":
            if f.get("options"):
                opt = f["options"][1] if len(f["options"]) > 1 else f["options"][0]
                steps.append(_step("select", loc, opt, f'Select "{opt}" in {label}'))
            continue
        if f["type"] == "checkbox":
            if f.get("required"):
                steps.append(_step("check", loc, None, f"Check {label}"))
            continue
        value = override.get(f.get("name"), sample_value(f))
        if value is None:
            continue
        steps.append(_step("fill", loc, value, f"Enter {label}"))
    return steps


def _submit(form: dict) -> Optional[dict]:
    if form.get("submit"):
        loc = _best(form["submit"].get("locators", []))
        if loc:
            return _step("click", loc, None, f'Click "{form["submit"]["text"]}"')
    return None


def _login_steps(login_page: Any, form: dict) -> list[dict]:
    steps = [_step("navigate", None, _path(login_page.url), "Open the sign-in page")]
    for f in form.get("fields", []):
        loc = _best(f.get("locators", []))
        if not loc:
            continue
        if f["type"] == "password":
            steps.append(_step("fill", loc, "{{password}}", "Enter the password"))
        elif f["type"] in ("email", "text"):
            steps.append(_step("fill", loc, "{{username}}", "Enter the username"))
    sub = _submit(form)
    if sub:
        steps.append(sub)
    return steps


def plan_from_discovery(discovery: Any, pages: list[Any]) -> list[PlannedTest]:
    tests: list[PlannedTest] = []
    if not pages:
        return tests
    login_ok = bool((discovery.login_result or {}).get("success"))
    login_page, login_form = None, None
    for p in pages:
        for form in p.forms or []:
            if form.get("has_password"):
                login_page, login_form = p, form
                break
        if login_form:
            break
    prefix_login = _login_steps(login_page, login_form) if (login_ok and login_form) else []

    def needs_login(page: Any) -> list[dict]:
        return list(prefix_login) if page.requires_login and prefix_login else []

    # 1. Page smoke checks (regression baseline of what discovery observed)
    for page in pages[:12]:
        if page.requires_login and not prefix_login:
            continue
        steps = needs_login(page) + [_step("navigate", None, _path(page.url), f"Open {_path(page.url)}")]
        if page.title:
            steps.append(_step("assert_title", None, _title_core(page.title), f'Title contains "{_title_core(page.title)}"'))
        h1 = next((h["text"] for h in page.headings or [] if h.get("level") == 1), None)
        if h1:
            steps.append(_step("assert_visible", {"strategy": "role", "value": "heading", "name": h1}, None, f'Heading "{h1}" is visible'))
        if len(steps) > len(needs_login(page)) + 1:
            tests.append(PlannedTest(
                f"Verify {(_title_core(page.title) or _path(page.url))} page loads", "smoke", "low",
                f"Opens {_path(page.url)} and checks the title and main heading observed during discovery.",
                steps, "discovered", ["page"]))

    # 2. Navigation
    by_path = {_path(p.url): p for p in pages}
    seen_links: set[str] = set()
    for page in pages[:4]:
        if page.requires_login and not prefix_login:
            continue
        for link in page.links or []:
            if not link.get("in_nav"):
                continue
            target_path = _path(link["href"])
            dest = by_path.get(target_path)
            if dest is None or target_path == _path(page.url) or target_path in seen_links:
                continue
            seen_links.add(target_path)
            loc = _best(link.get("locators", []))
            if not loc:
                continue
            # Log in first when either page needs a session (logged-in menus differ from anonymous ones).
            login = list(prefix_login) if prefix_login and (page.requires_login or dest.requires_login) else []
            steps = login + [
                _step("navigate", None, _path(page.url), f"Open {_path(page.url)}"),
                _step("click", loc, None, f'Click the "{link["text"]}" link'),
                _step("assert_url", None, target_path, f"URL contains {target_path}"),
            ]
            h1 = next((h["text"] for h in dest.headings or [] if h.get("level") == 1), None)
            if h1:
                steps.append(_step("assert_visible", {"strategy": "role", "value": "heading", "name": h1}, None, f'Heading "{h1}" is visible'))
            tests.append(PlannedTest(f'Verify navigation to "{link["text"]}"', "ui", "medium",
                                     f"Clicks the navigation link and checks that {target_path} opens.", steps, "discovered", ["navigation"]))
            if len(seen_links) >= 6:
                break

    # 3. Login
    if login_form:
        lp = _path(login_page.url)
        pwd = next((f for f in login_form["fields"] if f["type"] == "password"), None)
        pwd_loc = _best(pwd.get("locators", [])) if pwd else None
        if login_ok:
            landed = _path((discovery.login_result or {}).get("landed_on") or "/")
            tests.append(PlannedTest(
                "Verify login with valid credentials", "functional", "high",
                f"Signs in with the environment credentials and checks that {landed} opens (verified during discovery).",
                _login_steps(login_page, login_form) + [_step("assert_url", None, landed.split("?")[0], f"URL contains {landed.split('?')[0]}"),
                                                       _step("assert_url_not", None, lp.split("?")[0], "Sign-in page is no longer shown")],
                "confirmed", ["login"]))
        invalid = [_step("navigate", None, lp, "Open the sign-in page")]
        for f in login_form["fields"]:
            loc = _best(f.get("locators", []))
            if not loc:
                continue
            if f["type"] == "password":
                invalid.append(_step("fill", loc, "Wrong-{{random}}-pass", "Enter a wrong password"))
            elif f["type"] in ("email", "text"):
                invalid.append(_step("fill", loc, "{{username}}" if login_ok else "nobody@example.com", "Enter the username"))
        sub = _submit(login_form)
        if sub and pwd_loc:
            invalid += [sub, _step("assert_url", None, lp.split("?")[0], "Still on the sign-in page"),
                        _step("assert_visible", pwd_loc, None, "Password field is still shown")]
            tests.append(PlannedTest("Verify login rejects invalid credentials", "security", "high",
                                     "Signs in with a wrong password and expects to stay on the sign-in page.", invalid, "inferred", ["login"]))
            tests.append(PlannedTest("Validate mandatory fields on sign-in", "negative", "medium",
                                     "Submits the empty sign-in form and expects it not to sign in.",
                                     [_step("navigate", None, lp, "Open the sign-in page"), sub,
                                      _step("assert_url", None, lp.split("?")[0], "Still on the sign-in page"),
                                      _step("assert_visible", pwd_loc, None, "Password field is still shown")],
                                     "inferred", ["login"]))

    # 4. Other forms
    for page in pages:
        if page.requires_login and not prefix_login:
            continue
        for form in page.forms or []:
            if form.get("has_password") or not form.get("fields"):
                continue
            sub = _submit(form)
            if not sub:
                continue
            fp = _path(page.url).split("?")[0]
            name = form.get("name") or "form"
            base = needs_login(page) + [_step("navigate", None, _path(page.url), f"Open {fp}")]
            required = [f for f in form["fields"] if f.get("required")]
            if required:
                tests.append(PlannedTest(
                    f"Validate mandatory fields on {name}", "negative", "medium",
                    f"Submits {name} with all fields empty; required fields ({', '.join(f.get('label') or f.get('name') for f in required)}) should block submission.",
                    base + [sub, _step("assert_url", None, fp, f"Still on {fp}"), _step("assert_hidden", {"strategy": "role", "value": "status"}, None, "No success message")],
                    "inferred", ["form", "validation"]))
            email = next((f for f in form["fields"] if f["type"] == "email"), None)
            if email:
                tests.append(PlannedTest(
                    f"Verify invalid email is rejected on {name}", "negative", "medium",
                    f"Fills {name} with an invalid email address and expects submission to be blocked.",
                    base + _fill_form_steps(form, override={email.get("name"): "not-an-email"}) + [sub,
                        _step("assert_url", None, fp, f"Still on {fp}"),
                        _step("assert_hidden", {"strategy": "role", "value": "status"}, None, "No success message")],
                    "inferred", ["form", "validation"]))
            tests.append(PlannedTest(
                f"Validate form submission: {name}", "functional", "high",
                f"Fills {name} with valid generated data and submits it. Expectation (no error message shown) is inferred; review it.",
                base + _fill_form_steps(form) + [sub, _step("assert_hidden", {"strategy": "role", "value": "alert"}, None, "No error message is shown")],
                "inferred", ["form"]))
            for f in form["fields"]:
                if f.get("maxlength") and f["type"] in ("text", "textarea", "search") and int(f["maxlength"]) <= 500:
                    n = int(f["maxlength"])
                    loc = _best(f.get("locators", []))
                    if loc:
                        tests.append(PlannedTest(
                            f"Verify {f.get('label') or f.get('name')} accepts at most {n} characters", "boundary", "low",
                            f"Types {n + 5} characters and checks that the field keeps only {n} (maxlength observed during discovery).",
                            base + [_step("fill", loc, "a" * (n + 5), f"Type {n + 5} characters"),
                                    _step("assert_value", loc, "a" * n, f"Field contains {n} characters")],
                            "discovered", ["boundary"]))
                    break

    # 5. Tables
    for page in pages:
        if page.requires_login and not prefix_login:
            continue
        for table in page.tables or []:
            if not table.get("headers"):
                continue
            steps = needs_login(page) + [_step("navigate", None, _path(page.url), f"Open {_path(page.url)}")]
            # Browsers do not always expose <th> as columnheader, so check header text inside the table.
            if table.get("testid"):
                table_loc = {"strategy": "testid", "value": table["testid"]}
            elif table.get("caption"):
                table_loc = {"strategy": "role", "value": "table", "name": table["caption"]}
            else:
                table_loc = {"strategy": "css", "value": "table"}
            steps.append(_step("assert_visible", table_loc, None, "The table is visible"))
            for h in table["headers"][:5]:
                steps.append(_step("assert_text", table_loc, h, f'Column "{h}" is shown'))
            tests.append(PlannedTest(f"Verify {table.get('caption') or 'table'} shows its columns on {_title_core(page.title)}",
                                     "ui", "low", "Checks the table columns observed during discovery.", steps, "discovered", ["table"]))
    return tests


AI_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "scenarios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string", "enum": ["functional", "negative", "boundary", "security", "ui", "smoke"]},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "rationale": {"type": "string"},
                    "steps": {"type": "array", "items": STEP_SCHEMA},
                },
                "required": ["title", "category", "priority", "rationale", "steps"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scenarios"],
    "additionalProperties": False,
}


def ai_plan(discovery: Any, pages: list[Any], existing_titles: list[str], max_scenarios: int = 6) -> tuple[list[PlannedTest], dict]:
    """Ask the AI provider for extra scenarios. Raises LLMUnavailable when no provider is configured."""
    provider = get_provider()
    summary = [{
        "path": _path(p.url), "title": p.title, "requires_login": p.requires_login,
        "headings": [h["text"] for h in (p.headings or [])][:8],
        "forms": [{"name": f.get("name"), "fields": [{"label": x.get("label"), "type": x.get("type"), "required": x.get("required"),
                                                     "locator": _best(x.get("locators", []))} for x in f.get("fields", [])],
                   "submit": _best((f.get("submit") or {}).get("locators", []))} for f in (p.forms or [])],
        "links": [{"text": l["text"], "locator": _best(l.get("locators", []))} for l in (p.links or [])][:25],
        "buttons": [{"text": b["text"], "locator": _best(b.get("locators", []))} for b in (p.buttons or [])][:15],
    } for p in pages[:20]]
    system = (
        "You plan end-to-end UI tests. Propose additional high-value scenarios that the existing list does not cover: "
        "realistic user journeys across pages, negative paths and business rules visible in the UI. "
        "Use ONLY locators that appear in the discovery data. Use relative paths for navigate. Use {{username}} and "
        "{{password}} for credentials, {{timestamp}} for unique data. Every scenario must end with at least one assertion. "
        "Do not propose destructive actions such as deleting data or logging out. "
        f"Return at most {max_scenarios} scenarios."
    )
    user = (f"Existing scenarios: {existing_titles}\n\nDiscovery data:\n" + untrusted("website-discovery", summary))
    res = provider.complete_json(system=system, user=user, schema=AI_PLAN_SCHEMA, max_tokens=12000)
    known = known_locators_from_pages(pages)
    accepted: list[PlannedTest] = []
    rejected: list[dict] = []
    for sc in res.data.get("scenarios", [])[:max_scenarios]:
        steps, ok = [], True
        for st in sc.get("steps", []):
            tgt = st.get("target")
            if tgt and tgt.get("strategy") != "css":
                key = (tgt["strategy"], (tgt.get("name") or tgt.get("value") or "").strip().lower())
                if key not in known:
                    ok = False
                    rejected.append({"title": sc["title"], "reason": f"locator {key} was not seen during discovery"})
                    break
            options = {"name": st["variable_name"]} if st["action"] == "set_variable" and st.get("variable_name") else {}
            if st["action"] == "store_text" and st.get("variable_name"):
                st["value"] = st["variable_name"]
            steps.append({"action": st["action"], "target": tgt, "value": st.get("value"), "options": options,
                          "description": st.get("description", "")[:500]})
        if ok and steps:
            accepted.append(PlannedTest(sc["title"][:300], sc["category"], sc["priority"],
                                        "AI-proposed scenario (review before relying on it): " + sc.get("rationale", ""),
                                        steps, "inferred", ["ai"], engine="anthropic"))
    return accepted, {"model": res.model, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "rejected": rejected}
