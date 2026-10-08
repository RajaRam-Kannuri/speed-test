"""Small example module used to demonstrate testgen."""

from typing import List, Literal, Optional


def divide(a: int, b: int) -> float:
    """Divide a by b; both must be ints in [-100, 100] and b must not be zero."""
    for name, value in (("a", a), ("b", b)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an int")
        if not -100 <= value <= 100:
            raise ValueError(f"{name} out of range")
    if b == 0:
        raise ValueError("b must not be zero")
    return a / b


def greet(name: str, style: Literal["formal", "casual"] = "casual", title: Optional[str] = None) -> str:
    """Build a greeting for a name of 1-20 characters."""
    if not isinstance(name, str) or not 1 <= len(name) <= 20:
        raise ValueError("name must be a 1-20 character string")
    if style not in ("formal", "casual"):
        raise ValueError("unknown style")
    if title is not None and not isinstance(title, str):
        raise ValueError("title must be a string")
    who = f"{title} {name}" if title else name
    return f"Good day, {who}." if style == "formal" else f"Hi {who}!"


def average(values: List[float]) -> float:
    """Mean of 1-10 numbers."""
    if not isinstance(values, list) or not 1 <= len(values) <= 10:
        raise ValueError("values must be a list of 1-10 numbers")
    return sum(values) / len(values)
