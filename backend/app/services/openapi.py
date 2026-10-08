"""Parse OpenAPI 3.x, Swagger 2.0 and Postman v2.1 collections into endpoints."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import yaml

METHODS = ("get", "post", "put", "patch", "delete")


class SpecError(ValueError):
    pass


@dataclass
class ParsedEndpoint:
    method: str
    path: str
    operation_id: Optional[str] = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[dict] = field(default_factory=list)
    request_schema: Optional[dict] = None
    request_example: Any = None
    responses: dict[str, dict] = field(default_factory=dict)  # code -> {description, schema}
    security: list = field(default_factory=list)


@dataclass
class ParsedSpec:
    source_type: str
    title: str
    version: Optional[str]
    base_url: Optional[str]
    security_schemes: dict[str, Any]
    endpoints: list[ParsedEndpoint]


def load_document(text: str) -> dict:
    text = text.strip()
    if not text:
        raise SpecError("The specification is empty")
    try:
        data = json.loads(text) if text[:1] in "{[" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecError(f"Could not parse the specification as JSON or YAML: {str(exc)[:200]}") from exc
    if not isinstance(data, dict):
        raise SpecError("The specification must be a JSON or YAML object")
    return data


class RefResolver:
    def __init__(self, root: dict):
        self.root = root

    def get(self, ref: str) -> Any:
        if not ref.startswith("#/"):
            raise SpecError(f"Only local $ref values are supported ({ref})")
        node: Any = self.root
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise SpecError(f"Unresolvable $ref {ref}")
            node = node[part]
        return node

    def resolve(self, node: Any, depth: int = 0, stack: tuple = ()) -> Any:
        if depth > 12:
            return {}
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref = node["$ref"]
                if ref in stack:
                    return {"type": "object"}  # recursive schema: stop expanding
                return self.resolve(copy.deepcopy(self.get(ref)), depth + 1, stack + (ref,))
            return {k: self.resolve(v, depth + 1, stack) for k, v in node.items()}
        if isinstance(node, list):
            return [self.resolve(v, depth + 1, stack) for v in node]
        return node


def to_json_schema(schema: Any) -> Any:
    """Convert OpenAPI 3.0 schema quirks (nullable, example) to plain JSON Schema."""
    if isinstance(schema, list):
        return [to_json_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: to_json_schema(v) for k, v in schema.items() if k not in ("example", "examples", "xml", "externalDocs", "discriminator", "readOnly", "writeOnly", "deprecated")}
    if out.pop("nullable", False):
        t = out.get("type")
        if isinstance(t, str):
            out["type"] = [t, "null"]
        elif "type" not in out:
            out = {"anyOf": [out, {"type": "null"}]}
    return out


def _json_content(content: dict | None) -> tuple[Optional[dict], Any]:
    if not content:
        return None, None
    for ctype in ("application/json", "application/problem+json", "*/*"):
        if ctype in content:
            body = content[ctype] or {}
            example = body.get("example")
            if example is None and isinstance(body.get("examples"), dict) and body["examples"]:
                first = next(iter(body["examples"].values()))
                example = first.get("value") if isinstance(first, dict) else None
            return body.get("schema"), example
    for ctype, body in content.items():
        if "json" in ctype:
            return (body or {}).get("schema"), (body or {}).get("example")
    return None, None


def parse_openapi3(doc: dict, source_url: Optional[str]) -> ParsedSpec:
    r = RefResolver(doc)
    servers = doc.get("servers") or []
    base = servers[0].get("url") if servers and isinstance(servers[0], dict) else None
    if base and source_url and not urlsplit(base).scheme:
        base = urljoin(source_url, base)
    if not base and source_url:
        p = urlsplit(source_url)
        base = f"{p.scheme}://{p.netloc}"
    global_security = doc.get("security") or []
    endpoints = []
    for path, item in (doc.get("paths") or {}).items():
        item = r.resolve(item)
        shared = item.get("parameters", [])
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params = {(p.get("in"), p.get("name")): p for p in shared + op.get("parameters", []) if isinstance(p, dict)}
            schema, example = _json_content((op.get("requestBody") or {}).get("content"))
            responses = {}
            for code, resp in (op.get("responses") or {}).items():
                rs, _ = _json_content((resp or {}).get("content"))
                responses[str(code)] = {"description": (resp or {}).get("description", ""), "schema": to_json_schema(rs) if rs else None}
            endpoints.append(ParsedEndpoint(
                method=method.upper(), path=path, operation_id=op.get("operationId"),
                summary=op.get("summary") or op.get("description", "")[:200], tags=op.get("tags", []),
                parameters=[{"name": p.get("name"), "in": p.get("in"), "required": bool(p.get("required")),
                             "schema": to_json_schema(p.get("schema") or {}), "example": p.get("example")} for p in params.values()],
                request_schema=to_json_schema(schema) if schema else None, request_example=example,
                responses=responses, security=op.get("security", global_security) or [],
            ))
    return ParsedSpec("openapi", (doc.get("info") or {}).get("title", "API"), str(doc.get("openapi")), base,
                      r.resolve((doc.get("components") or {}).get("securitySchemes") or {}), endpoints)


def parse_swagger2(doc: dict, source_url: Optional[str]) -> ParsedSpec:
    r = RefResolver(doc)
    scheme = (doc.get("schemes") or ["https"])[0]
    host = doc.get("host") or (urlsplit(source_url).netloc if source_url else "")
    base = f"{scheme}://{host}{doc.get('basePath', '')}".rstrip("/") if host else None
    global_security = doc.get("security") or []
    endpoints = []
    for path, item in (doc.get("paths") or {}).items():
        item = r.resolve(item)
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params, body_schema = [], None
            for p in item.get("parameters", []) + op.get("parameters", []):
                if p.get("in") == "body":
                    body_schema = p.get("schema")
                elif p.get("in") in ("path", "query", "header"):
                    sch = {k: p[k] for k in ("type", "format", "enum", "minimum", "maximum", "minLength", "maxLength", "pattern") if k in p}
                    params.append({"name": p["name"], "in": p["in"], "required": bool(p.get("required")), "schema": sch, "example": p.get("x-example")})
            responses = {str(c): {"description": (v or {}).get("description", ""), "schema": to_json_schema((v or {}).get("schema"))}
                         for c, v in (op.get("responses") or {}).items()}
            endpoints.append(ParsedEndpoint(method.upper(), path, op.get("operationId"), op.get("summary", ""), op.get("tags", []),
                                            params, to_json_schema(body_schema) if body_schema else None, None, responses,
                                            op.get("security", global_security) or []))
    schemes = {}
    for name, sd in (doc.get("securityDefinitions") or {}).items():
        if sd.get("type") == "apiKey":
            schemes[name] = {"type": "apiKey", "in": sd.get("in"), "name": sd.get("name")}
        elif sd.get("type") == "basic":
            schemes[name] = {"type": "http", "scheme": "basic"}
        else:
            schemes[name] = sd
    return ParsedSpec("swagger", (doc.get("info") or {}).get("title", "API"), "2.0", base, schemes, endpoints)


def parse_postman(doc: dict) -> ParsedSpec:
    variables = {v.get("key"): v.get("value") for v in doc.get("variable", []) if isinstance(v, dict)}
    endpoints: list[ParsedEndpoint] = []
    base: Optional[str] = None

    def walk(items: list) -> None:
        nonlocal base
        for it in items:
            if "item" in it:
                walk(it["item"])
                continue
            req = it.get("request") or {}
            url = req.get("url")
            raw = url.get("raw") if isinstance(url, dict) else url
            if not raw:
                continue
            resolved = re.sub(r"\{\{(\w+)\}\}", lambda m: str(variables.get(m.group(1), m.group(0))), raw)
            parts = urlsplit(resolved)
            if parts.scheme and base is None:
                base = f"{parts.scheme}://{parts.netloc}"
            path = re.sub(r"/:(\w+)", r"/{\1}", parts.path or "/")
            body = None
            braw = (req.get("body") or {}).get("raw")
            if braw:
                try:
                    body = json.loads(braw)
                except ValueError:
                    body = None
            query = [{"name": q.get("key"), "in": "query", "required": False, "schema": {"type": "string"}, "example": q.get("value")}
                     for q in (url.get("query", []) if isinstance(url, dict) else []) if q.get("key")]
            params = query + [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}, "example": None}
                              for n in re.findall(r"\{(\w+)\}", path)]
            endpoints.append(ParsedEndpoint((req.get("method") or "GET").upper(), path, None, it.get("name", ""), [], params,
                                            None, body, {}, []))

    walk(doc.get("item", []))
    return ParsedSpec("postman", (doc.get("info") or {}).get("name", "Postman collection"), "postman-2.1", base, {}, endpoints)


def parse_spec(text: str, source_url: Optional[str] = None) -> ParsedSpec:
    doc = load_document(text)
    if str(doc.get("openapi", "")).startswith("3"):
        spec = parse_openapi3(doc, source_url)
    elif str(doc.get("swagger", "")) == "2.0":
        spec = parse_swagger2(doc, source_url)
    elif "item" in doc and "postman" in str((doc.get("info") or {}).get("schema", "")).lower():
        spec = parse_postman(doc)
    else:
        raise SpecError("Unrecognised format. Upload an OpenAPI 3.x, Swagger 2.0 or Postman v2.1 document.")
    if not spec.endpoints:
        raise SpecError("No endpoints were found in the specification")
    seen, unique = set(), []
    for ep in spec.endpoints:
        if (ep.method, ep.path) not in seen:
            seen.add((ep.method, ep.path))
            unique.append(ep)
    spec.endpoints = unique
    return spec
