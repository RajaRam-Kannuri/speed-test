"""Test Planning + Generation agents for APIs.

Expectations come from the specification: success codes from documented 2xx
responses, validation codes from documented 400/422 responses, auth codes from
documented 401/403, response bodies validated against documented schemas.
When a code is not documented the test uses a status range and says so.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from testgen.spec import ParamSpec
from testgen.values import values_for

from .llm import LLMUnavailable, get_provider, untrusted

BASE_VAR = "{{api_base_url}}"


@dataclass
class PlannedApiTest:
    title: str
    category: str
    priority: str
    description: str
    steps: list[dict[str, Any]]
    expectation_basis: str = "specified"
    tags: list[str] = field(default_factory=list)
    engine: str = "deterministic"


def _codes(ep: Any, wanted: tuple[str, ...]) -> list[int]:
    return sorted(int(c) for c in (ep.responses or {}) if c in wanted)


def success_code(ep: Any) -> tuple[Optional[int], Optional[dict]]:
    codes = sorted(c for c in (ep.responses or {}) if re.fullmatch(r"2\d\d", c))
    if not codes:
        return None, None
    return int(codes[0]), (ep.responses[codes[0]] or {}).get("schema")


def _expect_success(ep: Any) -> tuple[dict, str]:
    code, schema = success_code(ep)
    if code is None:
        return {"status_range": [200, 299]}, "Success code is not documented; any 2xx status is accepted."
    exp: dict[str, Any] = {"status": [code]}
    if schema and code != 204:
        exp["schema"] = schema
    return exp, f"Expects documented status {code}" + (" and validates the documented response schema." if "schema" in exp else ".")


def _expect_validation(ep: Any) -> tuple[dict, str]:
    codes = _codes(ep, ("400", "422"))
    if codes:
        return {"status": codes}, f"Expects documented validation status {'/'.join(map(str, codes))}."
    return {"status_range": [400, 499]}, "Validation status is not documented; any 4xx status is accepted."


def _expect_auth(ep: Any) -> tuple[dict, str]:
    codes = _codes(ep, ("401", "403"))
    if codes:
        return {"status": codes}, f"Expects documented status {'/'.join(map(str, codes))}."
    return {"status": [401, 403]}, "Auth failure status is not documented; 401 or 403 is accepted."


def sample_from_schema(schema: Optional[dict], name: str = "", depth: int = 0) -> Any:
    if not schema or depth > 6:
        return None
    if "example" in schema:
        return schema["example"]
    if "examples" in schema and isinstance(schema["examples"], list) and schema["examples"]:
        ex = schema["examples"][0]
        if isinstance(ex, str) and ("email" in name.lower() or schema.get("format") == "email"):
            local, _, domain = ex.partition("@")
            return f"{local}.{{{{random}}}}@{domain or 'example.com'}"
        return ex
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            options = [s for s in schema[key] if s.get("type") != "null"]
            if key == "allOf":
                merged: dict = {"type": "object", "properties": {}, "required": []}
                for s in schema[key]:
                    merged["properties"].update(s.get("properties", {}))
                    merged["required"] += s.get("required", [])
                return sample_from_schema(merged, name, depth + 1)
            if options:
                return sample_from_schema(options[0], name, depth + 1)
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    if t == "object" or "properties" in schema:
        return {k: sample_from_schema(v, k, depth + 1) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        item = sample_from_schema(schema.get("items") or {}, name, depth + 1)
        return [item] if item is not None else []
    if t == "integer":
        lo, hi = schema.get("minimum"), schema.get("maximum")
        return int(lo) if lo is not None else (int(hi) if hi is not None and hi < 1 else 1)
    if t == "number":
        return float(schema.get("minimum", 1))
    if t == "boolean":
        return True
    fmt = schema.get("format", "")
    if fmt == "email" or "email" in name.lower():
        return "qa.{{random}}@example.com"
    if fmt == "date-time":
        return "2025-01-15T10:00:00Z"
    if fmt == "date":
        return "2025-01-15"
    if fmt == "uuid":
        return "00000000-0000-4000-8000-000000000000"
    if fmt in ("uri", "url"):
        return "https://example.com"
    text = f"LorvenLax {name or 'value'} {{{{random}}}}"
    lo, hi = schema.get("minLength"), schema.get("maxLength")
    if hi is not None and len(text) > hi:
        text = ("Q{{random}}" if hi >= 10 else "Q" * max(int(lo or 1), 1))
    if lo is not None and len(text.replace("{{random}}", "12345678")) < lo:
        text = text + "x" * lo
    return text


def _object_schema(schema: Optional[dict]) -> Optional[dict]:
    if not schema:
        return None
    if schema.get("type") == "object" or "properties" in schema:
        return schema
    for key in ("allOf", "anyOf", "oneOf"):
        for s in schema.get(key, []):
            if s.get("type") == "object" or "properties" in s:
                return s
    return None


class ApiPlanContext:
    def __init__(self, endpoints: list[Any], security_schemes: dict):
        self.endpoints = endpoints
        self.schemes = security_schemes or {}

    def auth_headers(self, ep: Any) -> dict[str, str]:
        for requirement in ep.security or []:
            for name in requirement or {}:
                scheme = self.schemes.get(name, {})
                if scheme.get("type") == "http" and scheme.get("scheme", "").lower() == "bearer":
                    return {"Authorization": "Bearer {{api_token}}"}
                if scheme.get("type") == "apiKey" and scheme.get("in") == "header":
                    return {scheme.get("name", "X-API-Key"): "{{api_key}}"}
                if scheme.get("type") == "http" and scheme.get("scheme", "").lower() == "basic":
                    return {"Authorization": "Basic {{api_basic_credentials}}"}
                if scheme.get("type") == "oauth2":
                    return {"Authorization": "Bearer {{api_token}}"}
        return {}

    def creator_for(self, ep: Any) -> Optional[Any]:
        """A POST on the parent collection whose success response has an id, for chaining."""
        m = re.match(r"^(.*)/\{([^}]+)\}$", ep.path)
        if not m:
            return None
        parent = m.group(1)
        for other in self.endpoints:
            if other.method == "POST" and other.path.rstrip("/") == parent.rstrip("/"):
                code, schema = success_code(other)
                props = ((schema or {}).get("properties") or {}) if schema else {}
                if code and ("id" in props or m.group(2) in props):
                    return other
        return None


def _request(method: str, path: str, *, headers=None, query=None, body=None, raw_body=None, expect=None, store=None) -> dict:
    opts: dict[str, Any] = {"method": method, "url": BASE_VAR + path}
    if headers:
        opts["headers"] = headers
    if query:
        opts["query"] = query
    if body is not None:
        opts["body"] = body
    if raw_body is not None:
        opts["raw_body"] = raw_body
        opts.setdefault("headers", {})["content-type"] = "application/json"
    if expect:
        opts["expect"] = expect
    if store:
        opts["store"] = store
    return {"action": "api_request", "target": None, "value": None, "options": opts, "description": f"{method} {path}"}


def _path_values(ctx: ApiPlanContext, ep: Any) -> tuple[list[dict], dict[str, str]]:
    """Setup steps and path parameter values (chained from a create call when possible)."""
    setup: list[dict] = []
    values: dict[str, str] = {}
    params = [p for p in ep.parameters if p.get("in") == "path"]
    if not params:
        return setup, values
    creator = ctx.creator_for(ep)
    if creator is not None and ep.method != "POST":
        exp, _ = _expect_success(creator)
        _, schema = success_code(creator)
        key = params[-1]["name"] if params[-1]["name"] in ((schema or {}).get("properties") or {}) else "id"
        setup.append(_request("POST", creator.path, headers=ctx.auth_headers(creator) or None,
                              body=sample_from_schema(creator.request_schema) if creator.request_schema else creator.request_example,
                              expect={"status": exp.get("status")} if exp.get("status") else exp, store={"created_id": f"$.{key}"}))
        setup[-1]["description"] = f"Create a resource with POST {creator.path} (setup)"
        values[params[-1]["name"]] = "{{created_id}}"
    for p in params:
        if p["name"] not in values:
            ex = p.get("example")
            if ex is None:
                ex = sample_from_schema(p.get("schema") or {"type": "string"}, p["name"])
            values[p["name"]] = str(ex)
    return setup, values


def _fill_path(path: str, values: dict[str, str]) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: values.get(m.group(1), "1"), path)


def plan_endpoint(ctx: ApiPlanContext, ep: Any) -> list[PlannedApiTest]:
    tests: list[PlannedApiTest] = []
    label = f"{ep.method} {ep.path}"
    auth = ctx.auth_headers(ep)
    setup, pvals = _path_values(ctx, ep)
    path = _fill_path(ep.path, pvals)
    body_schema = _object_schema(ep.request_schema)
    base_body = None
    if ep.method in ("POST", "PUT", "PATCH"):
        base_body = sample_from_schema(ep.request_schema) if ep.request_schema else ep.request_example
    query = {p["name"]: str(p["example"] if p.get("example") is not None else sample_from_schema(p.get("schema") or {}, p["name"]))
             for p in ep.parameters if p.get("in") == "query" and p.get("required")}
    ok_exp, ok_note = _expect_success(ep)
    val_exp, val_note = _expect_validation(ep)

    def add(title: str, category: str, priority: str, desc: str, steps: list[dict], tags: list[str], basis: str = "specified") -> None:
        tests.append(PlannedApiTest(title, category, priority, desc, steps, basis, tags))

    add(f"{label} succeeds with a valid request", "functional", "high",
        f"Sends a valid request. {ok_note}",
        setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=base_body, expect=ok_exp)],
        ["positive", "schema"] if "schema" in ok_exp else ["positive"])

    if ep.security:
        a_exp, a_note = _expect_auth(ep)
        add(f"{label} rejects requests without credentials", "security", "high",
            f"Sends the request without credentials. {a_note}",
            setup + [_request(ep.method, path, query=query or None, body=base_body, expect=a_exp)], ["auth"])
        bad = {k: ("Bearer invalid-token-123" if v.startswith("Bearer") else "invalid-key-123") for k, v in auth.items()}
        if bad:
            add(f"{label} rejects an invalid token", "security", "high",
                f"Sends the request with an invalid credential. {a_note}",
                setup + [_request(ep.method, path, headers=bad, query=query or None, body=base_body, expect=a_exp)], ["auth"])

    if body_schema and isinstance(base_body, dict):
        props = body_schema.get("properties") or {}
        for name in (body_schema.get("required") or [])[:5]:
            body = copy.deepcopy(base_body)
            body.pop(name, None)
            add(f"{label} rejects a request missing required field '{name}'", "negative", "medium",
                f"Omits the required field '{name}'. {val_note}",
                setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=body, expect=val_exp)], ["validation"])
        n_type = 0
        for name, ps in props.items():
            t = ps.get("type")
            t = next((x for x in t if x != "null"), None) if isinstance(t, list) else t
            if t in ("string", "integer", "number", "boolean") and n_type < 4:
                body = copy.deepcopy(base_body)
                body[name] = 12345 if t == "string" else "not-a-number" if t in ("integer", "number") else "not-a-boolean"
                add(f"{label} rejects wrong type for '{name}'", "negative", "medium",
                    f"Sends a {type(body[name]).__name__} where the schema requires {t}. {val_note}",
                    setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=body, expect=val_exp)], ["validation"])
                n_type += 1
            if ps.get("format") == "email":
                body = copy.deepcopy(base_body)
                body[name] = "not-an-email"
                add(f"{label} rejects an invalid email format in '{name}'", "negative", "medium",
                    f"Sends an invalid email address. {val_note}",
                    setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=body, expect=val_exp)], ["validation"])
            enum = ps.get("enum") or next((s.get("enum") for s in ps.get("anyOf", []) if s.get("enum")), None)
            if enum:
                body = copy.deepcopy(base_body)
                body[name] = "NOT_A_VALID_OPTION"
                add(f"{label} rejects a value outside the allowed list for '{name}'", "negative", "medium",
                    f"Allowed values are {enum}. {val_note}",
                    setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=body, expect=val_exp)], ["validation"])
            if t == "string" and ps.get("maxLength"):
                n = int(ps["maxLength"])
                if n <= 5000:
                    body = copy.deepcopy(base_body)
                    body[name] = "a" * n
                    add(f"{label} accepts '{name}' at its maximum length ({n})", "boundary", "medium",
                        f"Uses exactly {n} characters, the documented maximum. {ok_note}",
                        setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=body, expect=ok_exp)], ["boundary"])
                    body = copy.deepcopy(base_body)
                    body[name] = "a" * (n + 1)
                    add(f"{label} rejects '{name}' longer than {n} characters", "boundary", "medium",
                        f"Uses {n + 1} characters, one more than allowed. {val_note}",
                        setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=body, expect=val_exp)], ["boundary"])
            if t == "string" and ps.get("minLength"):
                n = int(ps["minLength"])
                body = copy.deepcopy(base_body)
                body[name] = "a" * (n - 1)
                add(f"{label} rejects '{name}' shorter than {n} character(s)", "boundary", "medium",
                    f"Uses {n - 1} characters, one fewer than allowed. {val_note}",
                    setup + [_request(ep.method, path, headers=auth or None, query=query or None, body=body, expect=val_exp)], ["boundary"])
        add(f"{label} rejects malformed JSON", "negative", "medium", f"Sends a body that is not valid JSON. {val_note}",
            setup + [_request(ep.method, path, headers=auth or None, query=query or None, raw_body='{"broken": ', expect=val_exp)], ["validation"])
        if "409" in (ep.responses or {}):
            body = copy.deepcopy(base_body)
            unique_fields = [k for k, v in props.items() if v.get("format") == "email" or "email" in k.lower()] or list(props)[:1]
            set_steps = []
            for k in unique_fields:
                set_steps.append({"action": "set_variable", "target": None, "value": f"dup.{{{{random}}}}@example.com" if "email" in k.lower() else f"dup {{{{random}}}}",
                                  "options": {"name": f"dup_{k}"}, "description": f"Choose a value for {k}"})
                body[k] = f"{{{{dup_{k}}}}}"
            add(f"{label} rejects a duplicate resource", "negative", "medium",
                "Creates the same resource twice; the second request should be refused with documented status 409.",
                set_steps + [_request(ep.method, path, headers=auth or None, body=body, expect=ok_exp),
                             _request(ep.method, path, headers=auth or None, body=body, expect={"status": [409]})], ["duplicate"])

    for p in ep.parameters:
        if p.get("in") != "query":
            continue
        sch = p.get("schema") or {}
        t = sch.get("type")
        if t == "integer" and (sch.get("minimum") is not None or sch.get("maximum") is not None):
            spec = ParamSpec(name=p["name"], type="int", min=sch.get("minimum"), max=sch.get("maximum"))
            for v in values_for(spec):
                if v.value is None or isinstance(v.value, str):
                    continue
                q = dict(query, **{p["name"]: str(v.value)})
                if v.valid:
                    add(f"{label} accepts {p['name']}={v.value} ({v.label})", "boundary", "low", f"Boundary value. {ok_note}",
                        setup + [_request(ep.method, path, headers=auth or None, query=q, body=base_body, expect=ok_exp)], ["boundary"])
                else:
                    add(f"{label} rejects {p['name']}={v.value} ({v.label})", "boundary", "medium", f"Out-of-range value. {val_note}",
                        setup + [_request(ep.method, path, headers=auth or None, query=q, body=base_body, expect=val_exp)], ["boundary"])
        enum = sch.get("enum") or next((s.get("enum") for s in sch.get("anyOf", []) if s.get("enum")), None)
        if enum:
            q = dict(query, **{p["name"]: "NOT_A_VALID_OPTION"})
            add(f"{label} rejects an invalid '{p['name']}' value", "negative", "low", f"Allowed values are {enum}. {val_note}",
                setup + [_request(ep.method, path, headers=auth or None, query=q, body=base_body, expect=val_exp)], ["validation"])

    if "404" in (ep.responses or {}) and any(p.get("in") == "path" for p in ep.parameters):
        missing = {p["name"]: "999999999" for p in ep.parameters if p.get("in") == "path"}
        add(f"{label} returns 404 for a resource that does not exist", "negative", "medium",
            "Requests an id that does not exist. Expects documented status 404.",
            [_request(ep.method, _fill_path(ep.path, missing), headers=auth or None, body=base_body, expect={"status": [404]})], ["not-found"])
    return tests


AI_API_SCHEMA = {
    "type": "object",
    "properties": {"scenarios": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"}, "category": {"type": "string", "enum": ["functional", "negative", "boundary", "security"]},
            "method": {"type": "string"}, "path": {"type": "string"}, "body_json": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "expected_status": {"type": "array", "items": {"type": "integer"}}, "rationale": {"type": "string"}},
        "required": ["title", "category", "method", "path", "body_json", "expected_status", "rationale"],
        "additionalProperties": False}}},
    "required": ["scenarios"], "additionalProperties": False,
}


def ai_plan(ctx: ApiPlanContext, existing_titles: list[str], max_scenarios: int = 8) -> tuple[list[PlannedApiTest], dict]:
    provider = get_provider()
    summary = [{"method": e.method, "path": e.path, "summary": e.summary, "parameters": e.parameters,
                "request_schema": e.request_schema, "responses": {k: v.get("description") for k, v in (e.responses or {}).items()}}
               for e in ctx.endpoints[:40]]
    res = provider.complete_json(
        system=("You design API test scenarios that go beyond schema checks: business rules and edge cases implied by the "
                "specification. Expected status codes MUST be documented in the specification for that endpoint. "
                "Use only the listed endpoints. Paths must use concrete values or {{created_id}}-free literals. "
                f"Return at most {max_scenarios} scenarios."),
        user=f"Existing scenarios: {existing_titles}\n\n" + untrusted("api-specification", summary),
        schema=AI_API_SCHEMA, max_tokens=12000,
    )
    accepted, rejected = [], []
    by_key = {(e.method, e.path): e for e in ctx.endpoints}
    for sc in res.data.get("scenarios", [])[:max_scenarios]:
        ep = next((e for (m, p), e in by_key.items() if m == sc["method"].upper() and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", p), sc["path"])), None)
        if ep is None:
            rejected.append({"title": sc["title"], "reason": "endpoint not in specification"})
            continue
        documented = {int(c) for c in (ep.responses or {}) if c.isdigit()}
        if not set(sc["expected_status"]) <= documented:
            rejected.append({"title": sc["title"], "reason": "expected status not documented"})
            continue
        try:
            body = json.loads(sc["body_json"]) if sc.get("body_json") else None
        except ValueError:
            rejected.append({"title": sc["title"], "reason": "invalid body JSON"})
            continue
        accepted.append(PlannedApiTest(sc["title"][:300], sc["category"], "medium", "AI-proposed scenario: " + sc["rationale"],
                                       [_request(ep.method, sc["path"], headers=ctx.auth_headers(ep) or None, body=body,
                                                 expect={"status": sc["expected_status"]})], "specified", ["ai"], "anthropic"))
    return accepted, {"model": res.model, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "rejected": rejected}
