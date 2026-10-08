"""Draft a spec from a Python module's function signatures and type hints."""

from __future__ import annotations

import inspect
import typing
from pathlib import Path
from typing import Any, List, Optional

from .spec import FunctionSpec, ParamSpec, Spec

_TYPE_NAMES = {int: "int", float: "float", str: "str", bool: "bool", list: "list"}


def _param_from_annotation(name: str, annotation: Any) -> ParamSpec:
    param = ParamSpec(name=name)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # Optional[X] / X | None
    if args and type(None) in args and origin is not list:
        param.nullable = True
        rest = [a for a in args if a is not type(None)]
        if len(rest) == 1:
            annotation = rest[0]
            origin, args = typing.get_origin(annotation), typing.get_args(annotation)

    if origin is typing.Literal:
        param.choices = list(args)
        param.type = "any"
    elif origin is list or annotation is list:
        param.type = "list"
        if args:
            param.items = _param_from_annotation("item", args[0])
    elif annotation in _TYPE_NAMES:
        param.type = _TYPE_NAMES[annotation]
    return param


def spec_from_module(module, module_ref: str, only: Optional[List[str]] = None) -> Spec:
    functions: List[FunctionSpec] = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_") or obj.__module__ != module.__name__:
            continue
        if only and name not in only:
            continue
        try:
            hints = typing.get_type_hints(obj)
        except Exception:  # noqa: BLE001 - unresolvable forward refs etc.
            hints = {}
        params = []
        for pname, p in inspect.signature(obj).parameters.items():
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            param = _param_from_annotation(pname, hints.get(pname, Any))
            if p.default is not p.empty:
                param.default, param.has_default = p.default, True
            params.append(param)
        doc = inspect.getdoc(obj) or ""
        functions.append(FunctionSpec(name=name, parameters=params,
                                      description=doc.splitlines()[0] if doc else ""))
    return Spec(module=module_ref, functions=functions, base_dir=Path.cwd())
