"""Combine per-parameter values into concrete test cases.

Strategies:

* ``each``     - start from a baseline of nominal values and vary one parameter
                 at a time (every value appears in at least one case).
* ``pairwise`` - greedy all-pairs over the *valid* values, plus one case per
                 invalid value (invalid values are never combined, so a failure
                 points at exactly one bad input).
* ``exhaustive`` - full cartesian product of valid values (capped), plus the
                 invalid one-at-a-time cases.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .spec import FunctionSpec
from .values import BOUNDARY, INVALID, NOMINAL, Value, values_for

STRATEGIES = ("each", "pairwise", "exhaustive")
EXHAUSTIVE_CAP = 500


@dataclass
class TestCase:
    __test__ = False  # keep pytest from collecting this class

    id: str
    function: str
    inputs: Dict[str, Any]
    category: str  # nominal | boundary | invalid
    description: str
    expect: str = "unknown"  # "return" | "raises" | "unknown"
    expected: Any = None  # return value, or exception class name when expect == "raises"
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "function": self.function,
            "category": self.category,
            "description": self.description,
            "inputs": self.inputs,
            "expect": self.expect,
            "expected": self.expected,
            "notes": self.notes,
        }


def _category(values: List[Value]) -> str:
    cats = {v.category for v in values}
    if INVALID in cats:
        return INVALID
    if BOUNDARY in cats:
        return BOUNDARY
    return NOMINAL


def _describe(fn: FunctionSpec, chosen: Dict[str, Value], baseline: Dict[str, Value]) -> str:
    changed = [f"{name}={v.label}" for name, v in chosen.items() if v is not baseline[name]]
    return ", ".join(changed) if changed else "all parameters nominal"


def _pairwise(names: List[str], domains: Dict[str, List[Value]]) -> List[Dict[str, Value]]:
    """Greedy all-pairs (IPO-style horizontal growth, simplified)."""
    if len(names) < 2:
        return [{n: v} for n in names for v in domains[n]] or [{}]

    uncovered = set()
    for (i, a), (j, b) in itertools.combinations(enumerate(names), 2):
        for x in range(len(domains[a])):
            for y in range(len(domains[b])):
                uncovered.add((i, x, j, y))

    rows: List[Dict[str, Value]] = []
    while uncovered:
        # Seed the row with the first uncovered pair, then fill remaining
        # columns with whichever value covers the most new pairs.
        i, x, j, y = min(uncovered)
        idx: Dict[int, int] = {i: x, j: y}
        for k in range(len(names)):
            if k in idx:
                continue
            best, best_gain = 0, -1
            for cand in range(len(domains[names[k]])):
                gain = sum(
                    1
                    for m, mv in idx.items()
                    if (min(k, m), cand if k < m else mv, max(k, m), mv if k < m else cand) in uncovered
                )
                if gain > best_gain:
                    best, best_gain = cand, gain
            idx[k] = best
        for (a, xa), (b, xb) in itertools.combinations(sorted(idx.items()), 2):
            uncovered.discard((a, xa, b, xb))
        rows.append({names[k]: domains[names[k]][v] for k, v in idx.items()})
    return rows


def generate_cases(fn: FunctionSpec, strategy: str = "each") -> List[TestCase]:
    """Generate test cases for one function."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy '{strategy}' (expected one of {', '.join(STRATEGIES)})")

    names = [p.name for p in fn.parameters]
    all_values = {p.name: values_for(p) for p in fn.parameters}
    valid = {n: [v for v in vals if v.valid] for n, vals in all_values.items()}
    invalid = {n: [v for v in vals if not v.valid] for n, vals in all_values.items()}
    baseline = {n: next(v for v in valid[n] if v.category == NOMINAL) for n in names}

    combos: List[Dict[str, Value]] = []
    if strategy == "each":
        combos.append(dict(baseline))
        for n in names:
            for v in valid[n]:
                if v is not baseline[n]:
                    combos.append({**baseline, n: v})
    elif strategy == "pairwise":
        combos.extend(_pairwise(names, valid))
    else:
        product = itertools.product(*(valid[n] for n in names))
        for row in itertools.islice(product, EXHAUSTIVE_CAP):
            combos.append(dict(zip(names, row)))

    # Invalid values are always tested one at a time against the baseline.
    for n in names:
        for v in invalid[n]:
            combos.append({**baseline, n: v})

    cases: List[TestCase] = []
    seen = set()
    for chosen in combos:
        key = tuple((n, repr(chosen[n].value), type(chosen[n].value).__name__) for n in names)
        if key in seen:
            continue
        seen.add(key)
        category = _category(list(chosen.values()))
        case = TestCase(
            id=f"{fn.name}_{len(cases) + 1:03d}",
            function=fn.name,
            inputs={n: chosen[n].value for n in names},
            category=category,
            description=_describe(fn, chosen, baseline),
        )
        if category == INVALID and fn.raises_on_invalid:
            case.expect, case.expected = "raises", fn.raises_on_invalid
        cases.append(case)
    return cases


def generate_all(functions: List[FunctionSpec], strategy: str = "each",
                 only: Optional[List[str]] = None) -> List[TestCase]:
    out: List[TestCase] = []
    for fn in functions:
        if only and fn.name not in only:
            continue
        out.extend(generate_cases(fn, strategy))
    return out
