"""Requirements Analysis + Natural-Language Test agent.

Turns plain-English test instructions into structured, editable steps, using
the project's discovered pages to resolve real element locators. It reports
which parts it understood, which prerequisites are missing (e.g. credentials)
and what it needs clarified. Claude is used when configured; otherwise the
built-in rule engine handles common phrasing and says what it cannot map.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

from .llm import STEP_SCHEMA, LLMUnavailable, get_provider, untrusted
from .website_planner import _best, _fill_form_steps, _path, _step, _submit, _title_core, sample_value

VERBS = r"(?:open|launch|go|navigate|visit|browse|click|tap|press|enter|type|fill|input|select|choose|pick|check|tick|uncheck|verify|check|ensure|assert|confirm|validate|expect|see|wait|log|sign|login|create|add|submit|take|capture|search|store|save|logout)"


@dataclass
class NLPlan:
    title: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    interpretation: list[dict[str, Any]] = field(default_factory=list)  # {clause, steps: [i..], note}
    questions: list[str] = field(default_factory=list)
    prerequisites: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    engine: str = "deterministic"
    model: Optional[str] = None
    reply: str = ""


def split_clauses(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"(?:\.\s+|;\s*|\n+|,\s*(?:and\s+)?(?:then\s+)?|\s+then\s+|\s+and\s+then\s+)", text)
    out: list[str] = []
    for p in parts:
        out.extend(re.split(rf"\s+and\s+(?={VERBS}\b)", p, flags=re.I))
    return [c.strip(" .") for c in out if c and c.strip(" .")]


def _sim(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return difflib.SequenceMatcher(None, a, b).ratio()


def _singular(word: str) -> str:
    return re.sub(r"(ies)$", "y", re.sub(r"(?<!s)s$", "", word.strip().lower()))


class SiteModel:
    """Discovered pages and elements, used to resolve plain-English references."""

    def __init__(self, pages: list[Any], login_result: Optional[dict]):
        self.pages = pages
        self.login_result = login_result or {}
        self.login_page, self.login_form = None, None
        for p in pages:
            for f in p.forms or []:
                if f.get("has_password"):
                    self.login_page, self.login_form = p, f
                    break
            if self.login_form:
                break

    def page_by_name(self, name: str) -> Optional[Any]:
        name = re.sub(r"\b(page|screen|section|the|my)\b", "", name.lower()).strip()
        best, score = None, 0.0
        for p in self.pages:
            cands = [_title_core(p.title or ""), _path(p.url).strip("/").replace("-", " ").replace("/", " ")]
            cands += [h["text"] for h in (p.headings or []) if h.get("level") == 1]
            s = max(_sim(name, c) for c in cands if c) if any(cands) else 0
            if s > score:
                best, score = p, s
        return best if score >= 0.6 else None

    def page_for_path(self, path: str) -> Optional[Any]:
        for p in self.pages:
            if _path(p.url).split("?")[0] == path.split("?")[0]:
                return p
        return None

    def element(self, text: str, page: Optional[Any], kinds: tuple[str, ...] = ("button", "link")) -> Optional[tuple[dict, Any, str]]:
        """Find a clickable element by its visible text; prefer the current page."""
        pages = ([page] if page else []) + [p for p in self.pages if p is not page]
        best, best_score, best_page, best_kind = None, 0.0, None, ""
        for i, p in enumerate(pages):
            bonus = 0.05 if i == 0 and page else 0.0
            items: list[tuple[str, dict, str]] = []
            if "link" in kinds:
                items += [("link", l, l.get("text", "")) for l in (p.links or [])]
            if "button" in kinds:
                items += [("button", b, b.get("text", "")) for b in (p.buttons or [])]
                items += [("button", f["submit"], f["submit"].get("text", "")) for f in (p.forms or []) if f.get("submit")]
            for kind, item, label in items:
                s = _sim(text, label) + bonus
                if s > best_score and item.get("locators"):
                    best, best_score, best_page, best_kind = item, s, p, kind
        if best is None or best_score < 0.6:
            return None
        return _best(best["locators"]), best_page, best_kind if best_kind != "link" else ("link:" + best.get("href", ""))

    def field(self, text: str, page: Optional[Any]) -> Optional[dict]:
        pages = ([page] if page else []) + [p for p in self.pages if p is not page]
        best, score = None, 0.0
        for p in pages:
            for f in p.forms or []:
                for fld in f.get("fields", []):
                    s = max(_sim(text, fld.get("label") or ""), _sim(text, fld.get("name") or ""), _sim(text, fld.get("placeholder") or ""))
                    if s > score:
                        best, score = fld, s
        return _best(best["locators"]) if best and score >= 0.6 else None

    def form_for(self, thing: str) -> Optional[tuple[Any, dict]]:
        thing = _singular(thing)
        best, score = None, 0.0
        for p in self.pages:
            for f in p.forms or []:
                if f.get("has_password"):
                    continue
                cands = [f.get("name", ""), _title_core(p.title or ""), (f.get("submit") or {}).get("text", "")]
                s = max(_sim(thing, c) for c in cands if c) if any(cands) else 0
                if thing and any(thing in (c or "").lower() for c in cands):
                    s = max(s, 0.9)
                if s > score:
                    best, score = (p, f), s
        return best if score >= 0.6 else None


class RulePlanner:
    def __init__(self, site: SiteModel, variables: set[str], base_url: Optional[str]):
        self.site = site
        self.variables = variables
        self.base_url = base_url
        self.current: Optional[Any] = None
        self.plan = NLPlan(title="")
        self.last_created: Optional[str] = None
        self.logged_in = False

    def add(self, *steps: dict) -> list[int]:
        start = len(self.plan.steps)
        self.plan.steps.extend(steps)
        return list(range(start, len(self.plan.steps)))

    def need_var(self, name: str, reason: str, secret: bool = False) -> None:
        if name not in self.variables and not any(p["variable"] == name for p in self.plan.prerequisites):
            self.plan.prerequisites.append({"variable": name, "description": reason, "secret": secret})

    def goto(self, page: Any, how: str = "navigate") -> list[dict]:
        if self.current is page:
            return []
        if page.requires_login and not self.logged_in and self.site.login_form:
            steps = self.login_steps()
        else:
            steps = []
        if self.current is not None and self.current is not page:
            for link in self.current.links or []:
                if _path(link.get("href", "")).split("?")[0] == _path(page.url).split("?")[0] and link.get("locators"):
                    steps.append(_step("click", _best(link["locators"]), None, f'Click the "{link["text"]}" link'))
                    self.current = page
                    return steps
        steps.append(_step("navigate", None, _path(page.url), f"Open {_path(page.url)}"))
        self.current = page
        return steps

    def login_steps(self, invalid: bool = False) -> list[dict]:
        lp, lf = self.site.login_page, self.site.login_form
        steps = [_step("navigate", None, _path(lp.url), "Open the sign-in page")]
        for f in lf.get("fields", []):
            loc = _best(f.get("locators", []))
            if not loc:
                continue
            if f["type"] == "password":
                steps.append(_step("fill", loc, "Wrong-{{random}}-pass" if invalid else "{{password}}", "Enter a wrong password" if invalid else "Enter the password"))
            elif f["type"] in ("email", "text"):
                steps.append(_step("fill", loc, "{{username}}", "Enter the username"))
        sub = _submit(lf)
        if sub:
            steps.append(sub)
        self.need_var("username", "Username for signing in", False)
        if not invalid:
            self.need_var("password", "Password for signing in", True)
            self.logged_in = True
            landed = (self.site.login_result or {}).get("landed_on")
            self.current = self.site.page_for_path(_path(landed)) if landed else None
            steps.append(_step("assert_url_not", None, _path(lp.url).split("?")[0], "Sign-in page is no longer shown"))
        else:
            steps.append(_step("assert_url", None, _path(lp.url).split("?")[0], "Still on the sign-in page"))
            self.current = lp
        return steps

    # ----------------------------------------------------------------- clause handlers

    def handle(self, clause: str) -> tuple[list[int], str]:
        c = clause.strip()
        low = c.lower()
        quoted = re.findall(r"[\"“']([^\"”']+)[\"”']", c)

        url = re.search(r"https?://[^\s,]+", c)
        if re.match(r"^(open|launch|go to|navigate to|visit|browse to|load)\b", low) or re.match(r"^start (at|on)\b", low):
            if url:
                p = self.site.page_for_path(_path(url.group(0))) if self.base_url and url.group(0).startswith(self.base_url) else None
                self.current = p
                return self.add(_step("navigate", None, url.group(0), f"Open {url.group(0)}")), ""
            rest = re.sub(r"^(open|launch|go to|navigate to|visit|browse to|load|start at|start on)\s+", "", low)
            if re.search(r"\b(app|application|site|website|home ?page|portal|system)\b", rest) and not re.search(r"\b(dashboard|login|sign)\b", rest):
                p = self.site.page_for_path("/")
                self.current = p
                return self.add(_step("navigate", None, "/", "Open the application")), ""
            if re.search(r"\b(login|log in|sign ?in)\b", rest) and self.site.login_page:
                self.current = self.site.login_page
                return self.add(_step("navigate", None, _path(self.site.login_page.url), "Open the sign-in page")), ""
            page = self.site.page_by_name(rest)
            if page:
                return self.add(*self.goto(page)), ""
            return [], f"I could not find a page called \"{rest}\" among the discovered pages."

        if re.search(r"\b(log ?in|sign ?in|login)\b", low) and not re.search(r"\b(click|press)\b", low):
            if not self.site.login_form:
                return [], "I could not find a sign-in form. Run website discovery with login enabled, or describe the sign-in steps."
            invalid = bool(re.search(r"\b(invalid|wrong|incorrect|bad)\b", low))
            return self.add(*self.login_steps(invalid=invalid)), ""

        if re.search(r"\b(log ?out|sign ?out)\b", low):
            found = self.site.element("log out", self.current, ("link", "button")) or self.site.element("sign out", self.current, ("link", "button"))
            if found:
                return self.add(_step("click", found[0], None, "Log out")), ""
            return [], "I could not find a log-out control."

        m = re.match(r"^(?:create|add|register|make)\s+(?:a\s+|an\s+)?(?:new\s+)?(.+?)(?:\s+(?:named|called|with name)\s+[\"“']?([^\"”']+)[\"”']?)?$", c, re.I)
        if m:
            thing, name = m.group(1), m.group(2)
            found = self.site.form_for(thing)
            if not found:
                return [], f"I could not find a form for creating a {thing}."
            page, form = found
            steps = self.goto(page) if self.current is not page else []
            var = f"new_{re.sub(r'[^a-z0-9]+', '_', _singular(thing)).strip('_') or 'item'}_name"
            first_text = next((f for f in form.get("fields", []) if f["type"] in ("text", "textarea") and _best(f.get("locators", []))), None)
            override = {}
            if first_text:
                base_value = name or (sample_value(first_text) or "LorvenLax {{timestamp}}")
                steps.append({"action": "set_variable", "target": None, "value": base_value, "options": {"name": var},
                              "description": f"Choose a unique {first_text.get('label') or 'name'}"})
                override[first_text.get("name")] = "{{" + var + "}}"
                self.last_created = var
            steps += _fill_form_steps(form, override=override)
            sub = _submit(form)
            if sub:
                steps.append(sub)
            steps.append(_step("assert_hidden", {"strategy": "role", "value": "alert"}, None, "No error message is shown"))
            self.current = None  # destination after submit is unknown
            return self.add(*steps), ""

        m = re.match(r"^(?:click|tap|press|hit|choose)\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\s+(button|link|tab|menu|icon))?$", c, re.I)
        if m and not re.match(r"^press\s+(enter|tab|escape|esc)\b", low):
            label = quoted[0] if quoted else m.group(1)
            kinds = ("link",) if m.group(2) == "link" else ("button",) if m.group(2) == "button" else ("button", "link")
            found = self.site.element(label, self.current, kinds)
            if found:
                loc, page, kind = found
                if self.current is not None and page is not self.current and not page.requires_login:
                    pre = self.goto(page)
                else:
                    pre = []
                self.current = self.site.page_for_path(_path(kind[5:])) if kind.startswith("link:") else self.current
                return self.add(*pre, _step("click", loc, None, f'Click "{label}"')), ""
            role = "link" if m.group(2) == "link" else "button"
            self.plan.warnings.append(f'"{label}" was not found during discovery; using an unverified locator.')
            return self.add(_step("click", {"strategy": "role", "value": role, "name": label}, None, f'Click "{label}"')), ""

        m = re.match(r"^press\s+(enter|tab|escape|esc)\b", low)
        if m:
            key = {"esc": "Escape"}.get(m.group(1), m.group(1).capitalize())
            return self.add(_step("press", None, key, f"Press {key}")), ""

        fld = value = None
        m = re.match(r"^(?:enter|type|input|fill in|put)\s+[\"“']([^\"”']+)[\"”']\s+(?:in|into|as|for)\s+(?:the\s+)?(.+?)(?:\s+(?:field|box|input))?$", c, re.I)
        if m:
            value, fld = m.group(1), m.group(2)
        else:
            m = re.match(r"^(?:fill|fill in|set)\s+(?:the\s+)?(.+?)(?:\s+(?:field|box|input))?\s+(?:with|to)\s+[\"“']?([^\"”']+)[\"”']?$", c, re.I)
            if m:
                fld, value = m.group(1), m.group(2)
        if fld and value is not None:
            loc = self.site.field(fld, self.current)
            if not loc:
                self.plan.warnings.append(f'Field "{fld}" was not found during discovery; using its label as the locator.')
                loc = {"strategy": "label", "value": fld}
            return self.add(_step("fill", loc, value, f'Enter "{value}" into {fld}')), ""

        m = re.match(r"^(?:select|choose|pick)\s+[\"“']?([^\"”']+?)[\"”']?\s+(?:from|in)\s+(?:the\s+)?(.+?)(?:\s+(?:dropdown|list|menu|field))?$", c, re.I)
        if m:
            value, fld = m.group(1), m.group(2)
            loc = self.site.field(fld, self.current) or {"strategy": "label", "value": fld}
            return self.add(_step("select", loc, value, f'Select "{value}" in {fld}')), ""

        m = re.match(r"^(?:wait)\s+(?:for\s+)?(\d+)\s*(seconds?|secs?|s|ms|milliseconds?)\b", low)
        if m:
            ms = int(m.group(1)) * (1 if m.group(2).startswith("m") else 1000)
            return self.add(_step("wait_ms", None, str(ms), f"Wait {ms} ms")), ""

        if re.search(r"\b(screenshot|capture the (page|screen))\b", low):
            return self.add(_step("screenshot", None, "screenshot", "Take a screenshot")), ""

        if re.match(r"^(verify|check|ensure|assert|confirm|validate|expect|make sure|see)\b", low) or re.search(r"\bshould\b", low):
            return self.handle_assertion(c, low, quoted)

        return [], f"I could not turn \"{c}\" into a step."

    def handle_assertion(self, c: str, low: str, quoted: list[str]) -> tuple[list[int], str]:
        body = re.sub(r"^(verify|check|ensure|assert|confirm|validate|expect|make sure|see)\s+(that\s+)?", "", c, flags=re.I).strip()
        lbody = body.lower()
        if self.last_created and re.search(r"\b(appears?|listed|shows? up|is (shown|displayed|visible|present)|exists?|in the .*list)\b", lbody) \
                and re.search(r"\b(new|created|the)\b", lbody):
            return self.add(_step("assert_text", None, "{{" + self.last_created + "}}", "The created item is shown")), ""
        m = re.search(r"title\s+(?:is|contains|equals)\s+[\"“']?([^\"”']+)[\"”']?", body, re.I)
        if m:
            return self.add(_step("assert_title", None, m.group(1), f'Title contains "{m.group(1)}"')), ""
        m = re.search(r"url\s+(?:is|contains|includes|ends with)\s+[\"“']?([^\"”'\s]+)[\"”']?", body, re.I)
        if m:
            return self.add(_step("assert_url", None, m.group(1), f"URL contains {m.group(1)}")), ""
        if re.search(r"\b(error|validation)\s+(message|text)?\b", lbody):
            return self.add(_step("assert_visible", {"strategy": "role", "value": "alert"}, None, "An error message is shown")), ""
        if quoted:
            return self.add(_step("assert_text", None, quoted[0], f'Page shows "{quoted[0]}"')), ""
        m = re.match(r"^(?:the\s+)?(.+?)\s+(?:page\s+)?(?:is|are|gets?)?\s*(?:displayed|visible|shown|opens?|loads?|appears?|present)$", body, re.I)
        if m:
            subject = re.sub(r"\b(page|screen)\b", "", m.group(1), flags=re.I).strip()
            page = self.site.page_by_name(subject)
            if page:
                h1 = next((h["text"] for h in page.headings or [] if h.get("level") == 1), None)
                steps = [_step("assert_url", None, _path(page.url).split("?")[0], f"URL contains {_path(page.url).split('?')[0]}")]
                if h1:
                    steps.append(_step("assert_visible", {"strategy": "role", "value": "heading", "name": h1}, None, f'Heading "{h1}" is visible'))
                self.current = page
                return self.add(*steps), ""
            return self.add(_step("assert_text", None, subject, f'Page shows "{subject}"')), ""
        return [], f"I could not turn the check \"{c}\" into an assertion. Quote the exact text you expect to see."

    def run(self, text: str) -> NLPlan:
        clauses = split_clauses(text)
        for clause in clauses:
            idx, note = self.handle(clause)
            self.plan.interpretation.append({"clause": clause, "steps": idx, "note": note})
            if note:
                self.plan.questions.append(note + " Can you rephrase it, for example \"click the Save button\" or \"verify 'Welcome' is visible\"?")
        steps = self.plan.steps
        if steps and steps[0]["action"] not in ("navigate", "set_variable") and not any(s["action"] == "navigate" for s in steps[:1]):
            self.plan.steps.insert(0, _step("navigate", None, "/", "Open the application"))
            for item in self.plan.interpretation:
                item["steps"] = [i + 1 for i in item["steps"]]
            self.plan.warnings.append("Added a first step that opens the application home page.")
        if steps and not any(s["action"].startswith("assert") for s in steps):
            self.plan.questions.append("The test does not check anything yet. What should be true at the end (for example, a message or page that should appear)?")
        if not self.site.pages:
            self.plan.warnings.append("No website discovery is available for this project, so element names could not be verified. Run 'Test a Website' first for more reliable steps.")
        self.plan.title = (text.strip().split(".")[0][:120] or "Natural-language test").strip()
        return self.plan


NL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "reply": {"type": "string"},
        "steps": {"type": "array", "items": STEP_SCHEMA},
        "questions": {"type": "array", "items": {"type": "string"}},
        "prerequisites": {"type": "array", "items": {
            "type": "object",
            "properties": {"variable": {"type": "string"}, "description": {"type": "string"}, "secret": {"type": "boolean"}},
            "required": ["variable", "description", "secret"], "additionalProperties": False}},
    },
    "required": ["title", "reply", "steps", "questions", "prerequisites"],
    "additionalProperties": False,
}


def plan_with_ai(text: str, site: SiteModel, variables: set[str], history: list[dict]) -> NLPlan:
    provider = get_provider()
    pages = [{
        "path": _path(p.url), "title": p.title, "requires_login": p.requires_login,
        "headings": [h["text"] for h in (p.headings or [])][:6],
        "fields": [{"label": f.get("label"), "type": f.get("type"), "locator": _best(f.get("locators", []))}
                   for form in (p.forms or []) for f in form.get("fields", [])],
        "buttons": [{"text": (f.get("submit") or {}).get("text"), "locator": _best((f.get("submit") or {}).get("locators", []))} for f in (p.forms or []) if f.get("submit")]
        + [{"text": b["text"], "locator": _best(b.get("locators", []))} for b in (p.buttons or [])][:10],
        "links": [{"text": l["text"], "href": _path(l["href"]), "locator": _best(l.get("locators", []))} for l in (p.links or [])][:20],
    } for p in site.pages[:20]]
    system = (
        "You convert a tester's plain-English instructions into executable UI test steps for Playwright. "
        "Use relative paths for navigate. Prefer locators that appear in the discovery data. Reference credentials and "
        "other test data as {{variable}} placeholders and list each one the environment does not already define in "
        "'prerequisites' (mark passwords and tokens as secret). Use set_variable with {{timestamp}} for unique data "
        "and reuse that variable in later assertions. Always include assertions that check the outcome the tester "
        "described. If something is ambiguous or missing, still produce your best plan and ask in 'questions'. "
        "'reply' is a short, plain summary for the tester. Use store_text/set_variable 'variable_name' for variable names."
        f"\nVariables already defined in the environment: {sorted(variables)}"
    )
    user = text + "\n\nDiscovered application:\n" + untrusted("website-discovery", pages)
    res = provider.complete_json(system=system, user=user, schema=NL_SCHEMA, max_tokens=12000, history=history[-10:])
    d = res.data
    steps = []
    for st in d.get("steps", []):
        options = {}
        if st["action"] == "set_variable":
            options = {"name": st.get("variable_name") or "value"}
        value = st.get("value")
        if st["action"] == "store_text":
            value = st.get("variable_name") or value
        steps.append({"action": st["action"], "target": st.get("target"), "value": value, "options": options,
                      "description": (st.get("description") or "")[:500]})
    prereqs = [p for p in d.get("prerequisites", []) if p["variable"] not in variables]
    return NLPlan(title=d.get("title", "")[:200] or "AI-generated test", steps=steps, questions=d.get("questions", []),
                  prerequisites=prereqs, engine="anthropic", model=res.model, reply=d.get("reply", ""),
                  interpretation=[{"clause": text, "steps": list(range(len(steps))), "note": ""}])


def plan_instruction(text: str, pages: list[Any], login_result: Optional[dict], variables: set[str], base_url: Optional[str],
                     history: Optional[list[dict]] = None, prefer_ai: bool = True) -> NLPlan:
    site = SiteModel(pages, login_result)
    if prefer_ai:
        try:
            return plan_with_ai(text, site, variables, history or [])
        except LLMUnavailable as exc:
            plan = RulePlanner(site, variables, base_url).run(text)
            plan.warnings.insert(0, f"Planned by the built-in rule engine: {exc}")
            return plan
    return RulePlanner(site, variables, base_url).run(text)
