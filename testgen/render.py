"""Render test cases as data exports (JSON / CSV / Markdown) or pytest scripts."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .cases import TestCase
from .literal import to_json_safe, to_source
from .spec import Spec

FORMATS = ("json", "csv", "markdown")


# --------------------------------------------------------------------------- #
# Test case exports
# --------------------------------------------------------------------------- #

def _short(value, limit: int = 40) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _expected_text(case: TestCase) -> str:
    if case.expect == "raises":
        return f"raises {case.expected}"
    if case.expect in ("return", "repr"):
        return f"returns {_short(case.expected)}"
    return "(not recorded)"


def render_cases(cases: List[TestCase], fmt: str) -> str:
    if fmt == "json":
        return json.dumps([to_json_safe(c.to_dict()) for c in cases], indent=2, ensure_ascii=False) + "\n"

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "function", "category", "description", "inputs", "expected", "notes"])
        for c in cases:
            writer.writerow([
                c.id, c.function, c.category, c.description,
                json.dumps(to_json_safe(c.inputs), ensure_ascii=False),
                _expected_text(c), "; ".join(c.notes),
            ])
        return buf.getvalue()

    if fmt == "markdown":
        lines: List[str] = ["# Test cases", ""]
        by_fn: Dict[str, List[TestCase]] = {}
        for c in cases:
            by_fn.setdefault(c.function, []).append(c)
        for fn, fn_cases in by_fn.items():
            counts: Dict[str, int] = {}
            for c in fn_cases:
                counts[c.category] = counts.get(c.category, 0) + 1
            summary = ", ".join(f"{n} {cat}" for cat, n in counts.items())
            lines += [f"## `{fn}` ({len(fn_cases)} cases: {summary})", "",
                      "| ID | Category | Description | Inputs | Expected | Notes |",
                      "|----|----------|-------------|--------|----------|-------|"]
            for c in fn_cases:
                inputs = ", ".join(f"{k}={_short(v, 25)}" for k, v in c.inputs.items())
                row = [c.id, c.category, c.description, f"`{inputs}`" if inputs else "-",
                       _expected_text(c), "; ".join(c.notes)]
                lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
            lines.append("")
        return "\n".join(lines)

    raise ValueError(f"unknown format '{fmt}' (expected one of {', '.join(FORMATS)})")


# --------------------------------------------------------------------------- #
# Pytest script
# --------------------------------------------------------------------------- #

_HELPERS = '''

def _check(func, inputs, expect, expected):
    """Run ``func(**inputs)`` and compare against the recorded expectation."""
    if expect == "raises":
        with pytest.raises(Exception) as info:
            func(**inputs)
        assert type(info.value).__name__ == expected, (
            f"expected {expected}, got {type(info.value).__name__}: {info.value}"
        )
    elif expect == "raises_any":
        with pytest.raises(Exception):
            func(**inputs)
    elif expect == "return":
        actual = func(**inputs)
        if isinstance(expected, float):
            assert actual == pytest.approx(expected, nan_ok=True)
        else:
            assert actual == expected
            assert type(actual) is type(expected)
    elif expect == "repr":
        assert repr(func(**inputs)) == expected
    else:  # smoke test: must simply not raise
        func(**inputs)
'''


def _loader_source(spec: Spec, out_path: Optional[Path]) -> str:
    if not spec.module_is_path:
        return f'import importlib\n\ntarget = importlib.import_module({spec.module!r})\n'
    target = spec.module_path
    if out_path is not None:
        rel = os.path.relpath(target, out_path.resolve().parent).replace(os.sep, "/")
        path_expr = f"Path(__file__).resolve().parent / {rel!r}"
    else:
        path_expr = f"Path({str(target)!r})"
    return (
        "import importlib.util\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        f"_TARGET = ({path_expr}).resolve()\n"
        "sys.path.insert(0, str(_TARGET.parent))\n"
        "_spec = importlib.util.spec_from_file_location(_TARGET.stem, _TARGET)\n"
        "target = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(target)\n"
    )


def _case_expectation(case: TestCase):
    if case.expect == "unknown":
        return ("raises_any" if case.category == "invalid" else "smoke"), None
    return case.expect, case.expected


def render_script(spec: Spec, cases: List[TestCase], out_path: Optional[Path] = None,
                  source_name: str = "spec") -> str:
    by_fn: Dict[str, List[TestCase]] = {}
    for c in cases:
        by_fn.setdefault(c.function, []).append(c)

    parts = [
        f'"""Generated by testgen from {source_name}.\n\n'
        "Edit the spec and regenerate rather than editing this file by hand.\n"
        '"""\n\n'
        "import pytest\n",
        _loader_source(spec, out_path),
        _HELPERS,
    ]

    for fn, fn_cases in by_fn.items():
        const = "CASES_" + fn.replace(".", "_").upper()
        lines = [f"\n\n{const} = ["]
        for c in fn_cases:
            expect, expected = _case_expectation(c)
            comment = f"  # {c.description}" if c.description else ""
            lines.append(
                f"    pytest.param({to_source(c.inputs)}, {expect!r}, {to_source(expected)}, "
                f"id={c.id + '-' + c.category!r}),{comment}"
            )
            for note in c.notes:
                lines.append(f"    # NOTE {c.id}: {note}")
        lines.append("]\n")
        attr = "target." + fn
        lines.append(
            f'\n@pytest.mark.parametrize("inputs, expect, expected", {const})\n'
            f"def test_{fn.replace('.', '_')}(inputs, expect, expected):\n"
            f"    _check({attr}, inputs, expect, expected)\n"
        )
        parts.append("\n".join(lines))
    return "".join(parts)
