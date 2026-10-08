"""Test values for a single parameter via equivalence partitioning and
boundary value analysis.

Each parameter yields a list of ``Value`` objects. Valid values are split into
one *nominal* (a typical, middle-of-the-range value) and several *boundary*
values; *invalid* values fall outside the declared constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from .spec import ParamSpec

NOMINAL = "nominal"
BOUNDARY = "boundary"
INVALID = "invalid"

# Used when an int/float parameter declares no range.
_UNBOUNDED_INTS = [0, 1, -1, 2**31 - 1, -(2**31)]
_UNBOUNDED_FLOATS = [0.0, 1.5, -1.5, 1e-9, 1e12]


@dataclass(frozen=True)
class Value:
    value: Any
    category: str  # NOMINAL, BOUNDARY or INVALID
    label: str

    @property
    def valid(self) -> bool:
        return self.category != INVALID


def _dedupe(values: List[Value]) -> List[Value]:
    seen = set()
    out = []
    for v in values:
        key = (repr(v.value), type(v.value).__name__)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _is_excluded(param: ParamSpec, value: Any) -> bool:
    return any(value == ex and type(value) is type(ex) for ex in param.exclude)


def _numeric(param: ParamSpec) -> List[Value]:
    is_int = param.type == "int"
    step = 1 if is_int else 0.01
    cast = int if is_int else float
    lo, hi = param.min, param.max
    out: List[Value] = []

    if lo is not None and hi is not None:
        mid = cast((lo + hi) / 2) if not is_int else (int(lo) + int(hi)) // 2
        # Step away from the middle until we find a non-excluded value.
        for offset in range(1000):
            candidate = cast(round(mid + offset * step, 10))
            if candidate <= hi and not _is_excluded(param, candidate):
                mid = candidate
                break
        out.append(Value(mid, NOMINAL, "mid-range"))
    elif lo is not None:
        out.append(Value(cast(lo + (10 if is_int else 10.0)), NOMINAL, "above min"))
    elif hi is not None:
        out.append(Value(cast(hi - (10 if is_int else 10.0)), NOMINAL, "below max"))
    else:
        out.append(Value(cast(42), NOMINAL, "typical"))
        samples = _UNBOUNDED_INTS if is_int else _UNBOUNDED_FLOATS
        out.extend(Value(s, BOUNDARY, f"edge {s!r}") for s in samples)

    if lo is not None:
        out.append(Value(cast(lo), BOUNDARY, "min"))
        if hi is None or lo + step <= hi:
            out.append(Value(cast(round(lo + step, 10)), BOUNDARY, "min + 1 step"))
        out.append(Value(cast(round(lo - step, 10)), INVALID, "below min"))
    if hi is not None:
        out.append(Value(cast(hi), BOUNDARY, "max"))
        if lo is None or hi - step >= lo:
            out.append(Value(cast(round(hi - step, 10)), BOUNDARY, "max - 1 step"))
        out.append(Value(cast(round(hi + step, 10)), INVALID, "above max"))
    if (lo is None or lo <= 0) and (hi is None or hi >= 0):
        out.append(Value(cast(0), BOUNDARY, "zero"))

    out.append(Value("1" if is_int else "1.5", INVALID, "wrong type (str)"))
    return out


def _string(param: ParamSpec) -> List[Value]:
    lo, hi = param.min_length, param.max_length
    out: List[Value] = []
    if lo is not None and hi is not None:
        n = (lo + hi) // 2
    elif lo is not None:
        n = lo + 5
    elif hi is not None:
        n = max(hi // 2, 1) if hi else 0
    else:
        n = 5
    out.append(Value("a" * n, NOMINAL, f"length {n}"))

    if lo is None and hi is None:
        out.append(Value("", BOUNDARY, "empty"))
        out.append(Value(" ", BOUNDARY, "whitespace"))
        out.append(Value("héllo wörld ✓", BOUNDARY, "unicode"))
        out.append(Value("x" * 1000, BOUNDARY, "long (1000)"))
    if lo is not None:
        out.append(Value("a" * lo, BOUNDARY, f"min length {lo}"))
        if lo > 0:
            out.append(Value("a" * (lo - 1), INVALID, f"below min length {lo - 1}"))
    if hi is not None:
        out.append(Value("a" * hi, BOUNDARY, f"max length {hi}"))
        out.append(Value("a" * (hi + 1), INVALID, f"above max length {hi + 1}"))
    out.append(Value(123, INVALID, "wrong type (int)"))
    return out


def _list(param: ParamSpec) -> List[Value]:
    item = param.items or ParamSpec(name="item", type="int", min=0, max=9)
    item_values = [v.value for v in values_for(item) if v.valid and v.value is not None]
    sample = item_values[0] if item_values else 0

    lo, hi = param.min_length, param.max_length
    n = (lo + hi) // 2 if lo is not None and hi is not None else (lo or 0) + 3
    out: List[Value] = [Value([sample] * n, NOMINAL, f"{n} items")]
    if lo is None:
        out.append(Value([], BOUNDARY, "empty list"))
    else:
        out.append(Value([sample] * lo, BOUNDARY, f"min length {lo}"))
        if lo > 0:
            out.append(Value([sample] * (lo - 1), INVALID, f"below min length {lo - 1}"))
    if hi is not None:
        out.append(Value([sample] * hi, BOUNDARY, f"max length {hi}"))
        out.append(Value([sample] * (hi + 1), INVALID, f"above max length {hi + 1}"))
    if len(item_values) > 1:
        out.append(Value(item_values[: max(n, 2)], BOUNDARY, "mixed items"))
    invalid_items = [v.value for v in values_for(item) if not v.valid]
    if invalid_items and param.items is not None:
        out.append(Value([invalid_items[0]] * max(lo or 1, 1), INVALID, "invalid item"))
    out.append(Value("not a list", INVALID, "wrong type (str)"))
    return out


def values_for(param: ParamSpec) -> List[Value]:
    """Return the candidate test values for ``param``."""
    if param.choices:
        out = [Value(param.choices[0], NOMINAL, f"choice {param.choices[0]!r}")]
        out += [Value(c, BOUNDARY, f"choice {c!r}") for c in param.choices[1:]]
        numeric = [c for c in param.choices if isinstance(c, (int, float)) and not isinstance(c, bool)]
        bogus = max(numeric) + 1 if len(numeric) == len(param.choices) else "__not_a_choice__"
        out.append(Value(bogus, INVALID, "not in choices"))
    elif param.type in ("int", "float"):
        out = _numeric(param)
    elif param.type == "str":
        out = _string(param)
    elif param.type == "bool":
        out = [Value(True, NOMINAL, "true"), Value(False, BOUNDARY, "false")]
    elif param.type == "list":
        out = _list(param)
    else:  # any
        if param.has_default:
            out = [Value(param.default, NOMINAL, "default")]
        else:
            out = [Value(1, NOMINAL, "int")]
        out += [Value("text", BOUNDARY, "str"), Value(0, BOUNDARY, "zero"), Value([], BOUNDARY, "empty list")]

    if param.nullable:
        out.append(Value(None, BOUNDARY, "None"))
    elif param.type != "any":
        out.append(Value(None, INVALID, "None"))

    # Explicitly excluded values are invalid even when inside the valid range.
    fixed = [v for v in out if not (v.valid and _is_excluded(param, v.value))]
    if fixed and not any(v.category == NOMINAL for v in fixed):
        # The nominal value was excluded; promote the first remaining valid value.
        for i, v in enumerate(fixed):
            if v.valid:
                fixed[i] = Value(v.value, NOMINAL, v.label)
                break
    fixed += [Value(ex, INVALID, f"excluded {ex!r}") for ex in param.exclude]
    return _dedupe(fixed)
