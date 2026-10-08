"""Remove secrets from text before it is persisted, logged or sent to an AI provider."""

from __future__ import annotations

import re
from typing import Any, Iterable

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(bearer\s+)?[A-Za-z0-9._~+/=-]{6,}"),
    re.compile(r"(?i)((?:password|passwd|secret|api[_-]?key|token)['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]{3,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
]


def redact(text: str | None, secrets: Iterable[str] = ()) -> str | None:
    if not text:
        return text
    out = text
    for s in sorted({s for s in secrets if s and len(s) >= 3}, key=len, reverse=True):
        out = out.replace(s, REDACTED)
    for pattern in _PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + REDACTED, out)
    return out


def redact_obj(value: Any, secrets: Iterable[str] = ()) -> Any:
    secrets = list(secrets)
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [redact_obj(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: redact_obj(v, secrets) for k, v in value.items()}
    return value
