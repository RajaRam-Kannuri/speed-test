"""Load the module under test and record actual behaviour as expected results.

This "snapshot" oracle turns generated cases into characterization tests: the
function's current output is captured so future changes that alter behaviour
are caught. Cases whose expectation comes from the spec (``raises_on_invalid``)
keep that expectation; if the function currently disagrees a note is added,
since that usually points at a real bug.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import sys
from types import ModuleType
from typing import Callable, List

from .cases import TestCase
from .literal import is_literal
from .spec import Spec


def load_module(spec: Spec) -> ModuleType:
    if spec.module_is_path:
        path = spec.module_path
        if not path.exists():
            raise FileNotFoundError(f"module file not found: {path}")
        name = f"_testgen_target_{path.stem}"
        mod_spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(mod_spec)
        sys.path.insert(0, str(path.parent))
        try:
            mod_spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(path.parent))
        return module
    return importlib.import_module(spec.module)


def _get(module: ModuleType, name: str) -> Callable:
    obj = module
    for part in name.split("."):
        obj = getattr(obj, part)
    return obj


def record_expectations(spec: Spec, cases: List[TestCase]) -> List[TestCase]:
    module = load_module(spec)
    for case in cases:
        func = _get(module, case.function)
        try:
            result = func(**copy.deepcopy(case.inputs))
        except Exception as exc:  # noqa: BLE001 - we want every failure mode
            actual = ("raises", type(exc).__name__)
        else:
            actual = ("return", result)

        if case.expect == "raises":
            if actual != ("raises", case.expected):
                got = f"raised {actual[1]}" if actual[0] == "raises" else f"returned {actual[1]!r}"
                case.notes.append(
                    f"spec expects {case.expected} but function currently {got} - possible bug"
                )
            continue

        case.expect, case.expected = actual
        if actual[0] == "return" and not is_literal(actual[1]):
            case.expected = repr(actual[1])
            case.notes.append("return value is not a literal; compared via repr()")
            case.expect = "repr"
    return cases
