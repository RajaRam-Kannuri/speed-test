"""testgen: generate test cases and pytest scripts from function specs."""

from .cases import generate_cases
from .spec import FunctionSpec, ParamSpec, Spec, load_spec

__all__ = ["FunctionSpec", "ParamSpec", "Spec", "generate_cases", "load_spec"]
__version__ = "0.1.0"
