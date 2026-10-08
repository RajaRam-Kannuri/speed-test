"""Unit tests for agents. The AI provider is replaced by a stub here only;
production code paths call the real provider or report that none is configured."""

import json
from types import SimpleNamespace as NS

import pytest

from app.agents import api_planner, nl_agent, website_planner
from app.agents.failure_analysis import analyze_result
from app.agents.healing import rank_candidates
from app.agents.llm import LLMResult, LLMUnavailable, NoProvider, set_provider
from app.agents.validation import known_locators_from_pages
from app.services.openapi import SpecError, parse_spec


def page(url, title, requires_login=False, headings=(), forms=(), links=(), buttons=(), tables=()):
    return NS(url=url, title=title, requires_login=requires_login, headings=list(headings), forms=list(forms),
              links=list(links), buttons=list(buttons), tables=list(tables))


LOGIN_FORM = {"name": "Sign in form", "has_password": True, "fields": [
    {"type": "email", "name": "email", "label": "Email", "required": True, "locators": [{"strategy": "label", "value": "Email"}]},
    {"type": "password", "name": "password", "label": "Password", "required": True, "locators": [{"strategy": "label", "value": "Password"}]},
], "submit": {"text": "Sign in", "locators": [{"strategy": "role", "value": "button", "name": "Sign in"}]}}
CUSTOMER_FORM = {"name": "New customer form", "has_password": False, "fields": [
    {"type": "text", "name": "name", "label": "Company name", "required": True, "maxlength": "50",
     "locators": [{"strategy": "label", "value": "Company name"}]},
    {"type": "email", "name": "email", "label": "Contact email", "required": True, "locators": [{"strategy": "label", "value": "Contact email"}]},
    {"type": "select", "name": "plan", "label": "Plan", "options": ["Free", "Pro"], "locators": [{"strategy": "label", "value": "Plan"}]},
], "submit": {"text": "Create customer", "locators": [{"strategy": "role", "value": "button", "name": "Create customer"}]}}

PAGES = [
    page("https://app.test/dashboard", "Dashboard | Acme", True, [{"level": 1, "text": "Dashboard"}],
         links=[{"text": "Add a customer", "href": "https://app.test/customers/new", "in_nav": False,
                 "locators": [{"strategy": "role", "value": "link", "name": "Add a customer"}]},
                {"text": "Customers", "href": "https://app.test/customers", "in_nav": True,
                 "locators": [{"strategy": "role", "value": "link", "name": "Customers"}]}]),
    page("https://app.test/", "Home | Acme", False, [{"level": 1, "text": "Welcome"}],
         links=[{"text": "Sign in", "href": "https://app.test/login", "in_nav": True, "locators": [{"strategy": "role", "value": "link", "name": "Sign in"}]}]),
    page("https://app.test/login", "Sign in | Acme", False, [{"level": 1, "text": "Sign in"}], forms=[LOGIN_FORM]),
    page("https://app.test/customers/new", "New customer | Acme", True, [{"level": 1, "text": "New customer"}], forms=[CUSTOMER_FORM]),
    page("https://app.test/customers", "Customers | Acme", True, [{"level": 1, "text": "Customers"}],
         tables=[{"caption": "All customers", "headers": ["Name", "Email"], "row_count": 3, "testid": "customer-table"}]),
]
DISCOVERY = NS(login_result={"success": True, "landed_on": "https://app.test/dashboard"})


@pytest.fixture(autouse=True)
def no_ai():
    set_provider(NoProvider())
    yield
    set_provider(None)


def test_website_planner_covers_core_scenarios():
    tests = website_planner.plan_from_discovery(DISCOVERY, PAGES)
    titles = [t.title for t in tests]
    assert "Verify login with valid credentials" in titles
    assert "Verify login rejects invalid credentials" in titles
    assert any(t.startswith("Validate mandatory fields on New customer form") for t in titles)
    assert any("invalid email" in t for t in titles)
    assert any("accepts at most 50 characters" in t for t in titles)
    login = next(t for t in tests if t.title == "Verify login with valid credentials")
    assert login.expectation_basis == "confirmed"
    assert any(s["value"] == "{{password}}" for s in login.steps)  # credentials are never inlined
    # Pages behind login get a login prefix
    cust = next(t for t in tests if t.title.startswith("Verify Customers page loads"))
    assert cust.steps[0]["value"] == "/login"


def test_ai_scenarios_with_unknown_locators_are_rejected():
    class Stub:
        name, model = "anthropic", "stub"

        def complete_json(self, **kw):
            return LLMResult({"scenarios": [
                {"title": "Good", "category": "functional", "priority": "high", "rationale": "r", "steps": [
                    {"action": "navigate", "target": None, "value": "/customers", "variable_name": None, "description": ""},
                    {"action": "assert_visible", "target": {"strategy": "role", "value": "link", "name": "Add a customer"}, "value": None, "variable_name": None, "description": ""}]},
                {"title": "Hallucinated", "category": "functional", "priority": "high", "rationale": "r", "steps": [
                    {"action": "click", "target": {"strategy": "role", "value": "button", "name": "Delete everything"}, "value": None, "variable_name": None, "description": ""}]},
            ]}, "stub", 10, 10)

    set_provider(Stub())
    accepted, meta = website_planner.ai_plan(DISCOVERY, PAGES, [])
    assert [t.title for t in accepted] == ["Good"]
    assert meta["rejected"][0]["title"] == "Hallucinated"


def test_nl_rule_planner_example_instruction():
    plan = nl_agent.plan_instruction(
        "Open the application, log in with valid credentials, navigate to the dashboard, create a new customer, "
        "and verify that the customer appears in the customer list.", PAGES, DISCOVERY.login_result, set(), "https://app.test")
    actions = [s["action"] for s in plan.steps]
    assert plan.engine == "deterministic" and "built-in rule engine" in plan.warnings[0]
    assert actions[0] == "navigate" and "click" in actions and actions[-1] == "assert_text"
    assert plan.steps[-1]["value"].startswith("{{new_customer")
    assert {p["variable"] for p in plan.prerequisites} == {"username", "password"}
    assert next(p for p in plan.prerequisites if p["variable"] == "password")["secret"] is True


def test_nl_rule_planner_asks_when_it_cannot_map_a_clause():
    plan = nl_agent.plan_instruction("Open the application and frobnicate the widgets", PAGES, None, set(), "https://app.test")
    assert any("frobnicate" in q for q in plan.questions)
    assert any("does not check anything" in q for q in plan.questions)


def test_nl_plan_uses_ai_when_available():
    class Stub:
        name, model = "anthropic", "stub"

        def complete_json(self, **kw):
            assert "<untrusted_data" in kw["user"]  # discovery data is fenced as untrusted
            return LLMResult({"title": "Login", "reply": "ok", "questions": [], "prerequisites": [
                {"variable": "username", "description": "user", "secret": False}],
                "steps": [{"action": "navigate", "target": None, "value": "/login", "variable_name": None, "description": "Open"},
                          {"action": "assert_title", "target": None, "value": "Sign in", "variable_name": None, "description": "Title"}]},
                "stub-model", 1, 1)

    set_provider(Stub())
    plan = nl_agent.plan_instruction("log in", PAGES, None, {"username"}, "https://app.test")
    assert plan.engine == "anthropic" and plan.model == "stub-model"
    assert plan.prerequisites == []  # already defined variables are filtered out
    assert len(plan.steps) == 2


def test_no_provider_reports_unavailable():
    with pytest.raises(LLMUnavailable):
        NoProvider().complete_json(system="", user="", schema={})


def _result(status="failed", error="", steps=None, failed_index=None):
    return NS(id=None, test_case_id=None, status=status, error_message=error, failed_step_index=failed_index,
              step_results=steps or [])


@pytest.mark.parametrize("error,info,expected", [
    ("Error: Navigation blocked by network policy: address 10.0.0.1 is in a restricted range", {}, "environment_failure"),
    ('Error: Variable "password" is not defined in the environment', {}, "test_data_failure"),
    ("page.goto: net::ERR_CONNECTION_REFUSED at http://app/", {}, "environment_failure"),
    ("Error: HTTP status 500 for GET /api/x; body: boom", {}, "application_defect"),
    ("Error: response does not match schema: data/email must match format", {}, "application_defect"),
    ("TimeoutError: locator.click: Timeout 15000ms exceeded.\nCall log:\n  - waiting for getByRole('button', { name: 'Save' })",
     {"last_action": "click"}, "locator_failure"),
    ("Error: expect(locator).toBeVisible() failed\nLocator: getByText('Welcome')", {"last_action": "assert_visible"}, "assertion_failure"),
    ("Test timeout of 30000ms exceeded.", {}, "timeout"),
    ("SyntaxError: Unexpected token", {}, "automation_defect"),
    ("something odd", {}, "unknown"),
])
def test_failure_classification(error, info, expected):
    a = analyze_result(None, _result(error=error), info)
    assert a.category == expected
    assert 0 < a.confidence <= 1
    assert a.evidence["verified"]  # every analysis cites at least the error itself


def test_flaky_classification():
    a = analyze_result(None, _result(status="flaky", error=None), {}, ["Timeout waiting for x"])
    assert a.category == "potential_flaky" and a.confidence >= 0.8


def test_healing_ranks_similar_unique_element_first():
    target = {"strategy": "role", "value": "button", "name": "Sign in"}
    candidates = [
        {"tag": "button", "role": "", "text": "Log in", "visible": True},
        {"tag": "button", "role": "", "text": "Sign in now", "visible": True},
        {"tag": "a", "role": "", "text": "Help", "visible": True},
        {"tag": "button", "role": "", "text": "Sign in now", "visible": False},
    ]
    ranked = rank_candidates(target, candidates)
    assert ranked[0]["target"] == {"strategy": "role", "value": "button", "name": "Sign in now"}
    assert all(r["target"]["name"] != "Help" for r in ranked if r["target"].get("name"))
    assert ranked[0]["confidence"] >= 0.7 and "similarity" in ranked[0]["rationale"]


def test_healing_offers_nothing_when_no_candidate_is_similar():
    assert rank_candidates({"strategy": "role", "value": "link", "name": "Dashboard"},
                           [{"tag": "a", "text": "About", "visible": True}, {"tag": "a", "text": "Contact", "visible": True}]) == []


OPENAPI = {
    "openapi": "3.0.3", "info": {"title": "Pets", "version": "1"}, "servers": [{"url": "https://pets.example.com/v1"}],
    "components": {
        "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}},
        "schemas": {"Pet": {"type": "object", "required": ["name"], "properties": {
            "id": {"type": "integer"}, "name": {"type": "string", "minLength": 2, "maxLength": 20},
            "tag": {"type": "string", "nullable": True}}}},
    },
    "paths": {
        "/pets": {
            "get": {"parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 50}}],
                    "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}}}}}},
            "post": {"security": [{"key": []}],
                     "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}},
                     "responses": {"201": {"description": "created", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}},
                                   "400": {"description": "bad"}}},
        },
        "/pets/{petId}": {"get": {"parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}],
                                  "responses": {"200": {"description": "ok"}, "404": {"description": "missing"}}}},
    },
}


def test_openapi_parsing_resolves_refs_and_nullable():
    spec = parse_spec(json.dumps(OPENAPI))
    assert spec.base_url == "https://pets.example.com/v1"
    post = next(e for e in spec.endpoints if e.method == "POST")
    assert post.request_schema["properties"]["tag"]["type"] == ["string", "null"]
    assert post.security == [{"key": []}]
    assert set(post.responses) == {"201", "400"}


def test_openapi_yaml_swagger_and_postman():
    yaml_spec = "openapi: 3.1.0\ninfo: {title: Y, version: '1'}\nservers: [{url: 'https://y.example.com'}]\npaths:\n  /ping:\n    get:\n      responses: {'200': {description: ok}}\n"
    assert parse_spec(yaml_spec).endpoints[0].path == "/ping"
    swagger = {"swagger": "2.0", "info": {"title": "S"}, "host": "s.example.com", "basePath": "/api", "schemes": ["https"],
               "paths": {"/items": {"post": {"parameters": [{"in": "body", "name": "b", "schema": {"type": "object", "required": ["n"], "properties": {"n": {"type": "string"}}}}],
                                             "responses": {"200": {"description": "ok"}}}}}}
    s = parse_spec(json.dumps(swagger))
    assert s.base_url == "https://s.example.com/api" and s.endpoints[0].request_schema["required"] == ["n"]
    postman = {"info": {"name": "P", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
               "variable": [{"key": "base", "value": "https://p.example.com"}],
               "item": [{"name": "folder", "item": [{"name": "Get user", "request": {"method": "GET", "url": {"raw": "{{base}}/users/:id"}}}]}]}
    p = parse_spec(json.dumps(postman))
    assert p.base_url == "https://p.example.com" and p.endpoints[0].path == "/users/{id}"
    with pytest.raises(SpecError):
        parse_spec('{"hello": "world"}')


def test_api_planner_derives_expectations_from_spec():
    spec = parse_spec(json.dumps(OPENAPI))
    ctx = api_planner.ApiPlanContext(spec.endpoints, spec.security_schemes)
    post = next(e for e in spec.endpoints if e.method == "POST")
    tests = {t.title: t for t in api_planner.plan_endpoint(ctx, post)}
    ok = tests["POST /pets succeeds with a valid request"].steps[-1]["options"]
    assert ok["expect"]["status"] == [201] and "schema" in ok["expect"]
    assert ok["headers"] == {"X-Key": "{{api_key}}"}
    missing = tests["POST /pets rejects a request missing required field 'name'"].steps[-1]["options"]
    assert missing["expect"] == {"status": [400]}  # documented validation code
    noauth = tests["POST /pets rejects requests without credentials"].steps[-1]["options"]
    assert noauth["expect"] == {"status": [401, 403]} and "headers" not in noauth  # undocumented -> stated range
    assert "POST /pets accepts 'name' at its maximum length (20)" in tests
    assert "POST /pets rejects 'name' shorter than 2 character(s)" in tests
    get = next(e for e in spec.endpoints if e.method == "GET" and e.path == "/pets")
    gtitles = [t.title for t in api_planner.plan_endpoint(ctx, get)]
    assert "GET /pets rejects limit=0 (below min)" in gtitles and "GET /pets accepts limit=50 (max)" in gtitles
    item = next(e for e in spec.endpoints if e.path == "/pets/{petId}")
    item_tests = {t.title: t for t in api_planner.plan_endpoint(ctx, item)}
    chained = item_tests["GET /pets/{petId} succeeds with a valid request"].steps
    assert chained[0]["options"]["store"] == {"created_id": "$.id"} and chained[1]["options"]["url"].endswith("{{created_id}}")
    assert "GET /pets/{petId} returns 404 for a resource that does not exist" in item_tests


def test_known_locators_include_discovered_elements():
    known = known_locators_from_pages(PAGES)
    assert ("label", "company name") in known and ("role", "sign in") in known and ("testid", "customer-table") in known
