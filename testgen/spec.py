"""Spec model: describes the functions under test and their parameters.

A spec file is JSON shaped like::

    {
      "module": "examples/calculator.py",
      "functions": [
        {
          "name": "divide",
          "raises_on_invalid": "ValueError",
          "parameters": [
            {"name": "a", "type": "int", "min": -100, "max": 100},
            {"name": "b", "type": "int", "min": -100, "max": 100, "exclude": [0]}
          ]
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

SUPPORTED_TYPES = ("int", "float", "str", "bool", "list", "any")


class SpecError(ValueError):
    """Raised when a spec file is malformed."""


@dataclass
class ParamSpec:
    name: str
    type: str = "any"
    min: Optional[float] = None
    max: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    choices: Optional[List[Any]] = None
    exclude: List[Any] = field(default_factory=list)
    nullable: bool = False
    items: Optional["ParamSpec"] = None  # element type for lists
    default: Any = None
    has_default: bool = False

    @classmethod
    def from_dict(cls, data: dict, where: str = "parameter") -> "ParamSpec":
        if "name" not in data:
            raise SpecError(f"{where}: missing 'name'")
        ptype = data.get("type", "any")
        if ptype not in SUPPORTED_TYPES:
            raise SpecError(
                f"{where} '{data['name']}': unsupported type '{ptype}' "
                f"(expected one of {', '.join(SUPPORTED_TYPES)})"
            )
        items = data.get("items")
        if items is not None:
            items = cls.from_dict({"name": "item", **items}, f"{where} '{data['name']}' items")
        param = cls(
            name=data["name"],
            type=ptype,
            min=data.get("min"),
            max=data.get("max"),
            min_length=data.get("min_length"),
            max_length=data.get("max_length"),
            choices=data.get("choices"),
            exclude=list(data.get("exclude", [])),
            nullable=bool(data.get("nullable", False)),
            items=items,
            default=data.get("default"),
            has_default="default" in data,
        )
        if param.min is not None and param.max is not None and param.min > param.max:
            raise SpecError(f"{where} '{param.name}': min > max")
        if (
            param.min_length is not None
            and param.max_length is not None
            and param.min_length > param.max_length
        ):
            raise SpecError(f"{where} '{param.name}': min_length > max_length")
        return param

    def to_dict(self) -> dict:
        out: dict = {"name": self.name, "type": self.type}
        for key in ("min", "max", "min_length", "max_length", "choices"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.exclude:
            out["exclude"] = self.exclude
        if self.nullable:
            out["nullable"] = True
        if self.items is not None:
            items = self.items.to_dict()
            items.pop("name")
            out["items"] = items
        if self.has_default:
            out["default"] = self.default
        return out


@dataclass
class FunctionSpec:
    name: str
    parameters: List[ParamSpec] = field(default_factory=list)
    raises_on_invalid: Optional[str] = None
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "FunctionSpec":
        if "name" not in data:
            raise SpecError("function entry missing 'name'")
        where = f"function '{data['name']}'"
        params = [ParamSpec.from_dict(p, where) for p in data.get("parameters", [])]
        names = [p.name for p in params]
        if len(names) != len(set(names)):
            raise SpecError(f"{where}: duplicate parameter names")
        return cls(
            name=data["name"],
            parameters=params,
            raises_on_invalid=data.get("raises_on_invalid"),
            description=data.get("description", ""),
        )

    def to_dict(self) -> dict:
        out: dict = {"name": self.name}
        if self.description:
            out["description"] = self.description
        if self.raises_on_invalid:
            out["raises_on_invalid"] = self.raises_on_invalid
        out["parameters"] = [p.to_dict() for p in self.parameters]
        return out


@dataclass
class Spec:
    module: str
    functions: List[FunctionSpec]
    base_dir: Path = field(default_factory=Path.cwd)

    @classmethod
    def from_dict(cls, data: dict, base_dir: Optional[Path] = None) -> "Spec":
        if "module" not in data:
            raise SpecError("spec missing 'module'")
        functions = [FunctionSpec.from_dict(f) for f in data.get("functions", [])]
        if not functions:
            raise SpecError("spec defines no functions")
        return cls(module=data["module"], functions=functions, base_dir=base_dir or Path.cwd())

    def to_dict(self) -> dict:
        return {"module": self.module, "functions": [f.to_dict() for f in self.functions]}

    @property
    def module_is_path(self) -> bool:
        return self.module.endswith(".py") or "/" in self.module or "\\" in self.module

    @property
    def module_path(self) -> Path:
        """Absolute path to the target file (only valid when module_is_path)."""
        path = Path(self.module)
        return path if path.is_absolute() else (self.base_dir / path).resolve()

    def function(self, name: str) -> FunctionSpec:
        for fn in self.functions:
            if fn.name == name:
                return fn
        raise SpecError(f"no function named '{name}' in spec")


def load_spec(path: str | Path) -> Spec:
    """Load a JSON spec. Relative module paths resolve against the current directory."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path}: invalid JSON: {exc}") from exc
    return Spec.from_dict(data)
