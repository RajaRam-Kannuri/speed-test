"""Convert Python values to source code that evaluates back to the same value."""

from __future__ import annotations

import math
from typing import Any

_SCALARS = (bool, int, str, bytes, type(None))


def is_literal(value: Any) -> bool:
    if isinstance(value, _SCALARS) or isinstance(value, float):
        return True
    if isinstance(value, (list, tuple, set, frozenset)):
        return all(is_literal(v) for v in value)
    if isinstance(value, dict):
        return all(is_literal(k) and is_literal(v) for k, v in value.items())
    return False


def to_source(value: Any) -> str:
    """Return Python source for ``value``. Raises TypeError for non-literals."""
    if isinstance(value, float):
        if math.isnan(value):
            return 'float("nan")'
        if math.isinf(value):
            return 'float("inf")' if value > 0 else 'float("-inf")'
        return repr(value)
    if isinstance(value, _SCALARS):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(to_source(v) for v in value) + "]"
    if isinstance(value, tuple):
        inner = ", ".join(to_source(v) for v in value)
        return f"({inner},)" if len(value) == 1 else f"({inner})"
    if isinstance(value, (set, frozenset)):
        if not value:
            return "set()" if isinstance(value, set) else "frozenset()"
        inner = "{" + ", ".join(sorted(to_source(v) for v in value)) + "}"
        return inner if isinstance(value, set) else f"frozenset({inner})"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{to_source(k)}: {to_source(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"cannot express {type(value).__name__} as a literal")


def to_json_safe(value: Any) -> Any:
    """Best-effort conversion for JSON/CSV exports."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return value.decode("utf-8", "backslashreplace")
    if isinstance(value, (bool, int, float, str, type(None))):
        return value
    return repr(value)
