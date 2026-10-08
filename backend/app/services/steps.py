"""The step vocabulary shared by the visual builder, AI agents and the code generator.

A test case is an ordered list of structured steps. AI agents only ever emit
steps (validated data); executable code is produced by ``codegen`` from steps.
"""

from __future__ import annotations

from dataclasses import dataclass

LOCATOR_STRATEGIES = ("role", "label", "text", "placeholder", "testid", "css", "title", "alt")
ARIA_ROLES = {
    "button", "link", "textbox", "checkbox", "radio", "combobox", "listbox", "option", "heading", "row", "cell",
    "columnheader", "table", "tab", "tabpanel", "menuitem", "menu", "dialog", "alert", "status", "img", "list",
    "listitem", "navigation", "main", "banner", "form", "searchbox", "spinbutton", "switch", "slider", "region",
}


@dataclass(frozen=True)
class ActionSpec:
    label: str
    target: str  # "required" | "optional" | "none"
    value: str  # "required" | "optional" | "none"
    kind: str  # "ui" | "api" | "any"
    assertion: bool = False
    value_label: str = "Value"
    help: str = ""


ACTIONS: dict[str, ActionSpec] = {
    "navigate": ActionSpec("Navigate", "none", "required", "ui", value_label="URL or path", help="Open a page"),
    "click": ActionSpec("Click", "required", "none", "ui", help="Click an element"),
    "fill": ActionSpec("Type", "required", "required", "ui", value_label="Text", help="Enter text into a field"),
    "select": ActionSpec("Select", "required", "required", "ui", value_label="Option", help="Choose a dropdown option"),
    "check": ActionSpec("Check", "required", "none", "ui", help="Tick a checkbox"),
    "uncheck": ActionSpec("Uncheck", "required", "none", "ui", help="Clear a checkbox"),
    "press": ActionSpec("Press key", "optional", "required", "ui", value_label="Key", help="Press a key, e.g. Enter"),
    "wait_for": ActionSpec("Wait for element", "required", "none", "ui", help="Wait until an element appears"),
    "wait_ms": ActionSpec("Wait", "none", "required", "any", value_label="Milliseconds", help="Pause (max 30 s)"),
    "assert_visible": ActionSpec("Assert visible", "required", "none", "ui", True, help="Element is visible"),
    "assert_hidden": ActionSpec("Assert hidden", "required", "none", "ui", True, help="Element is not visible"),
    "assert_text": ActionSpec("Assert text", "optional", "required", "ui", True, "Expected text", "Page or element contains text"),
    "assert_no_text": ActionSpec("Assert text absent", "none", "required", "ui", True, "Text", "Page does not contain text"),
    "assert_value": ActionSpec("Assert field value", "required", "required", "ui", True, "Expected value"),
    "assert_count": ActionSpec("Assert count", "required", "required", "ui", True, "Expected count"),
    "assert_url": ActionSpec("Assert URL", "none", "required", "ui", True, "URL contains", "Current URL contains text"),
    "assert_url_not": ActionSpec("Assert URL changed", "none", "required", "ui", True, "URL does not contain"),
    "assert_title": ActionSpec("Assert title", "none", "required", "ui", True, "Title contains"),
    "screenshot": ActionSpec("Screenshot", "none", "optional", "ui", value_label="Name", help="Capture the page"),
    "store_text": ActionSpec("Extract text", "required", "required", "ui", value_label="Variable name", help="Save element text to a variable"),
    "set_variable": ActionSpec("Store variable", "none", "required", "any", value_label="Value", help="Save a value for later steps"),
    "api_request": ActionSpec("API request", "none", "none", "api", True, help="Send an HTTP request and check the response"),
}

UI_ACTIONS = {k for k, v in ACTIONS.items() if v.kind == "ui"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def describe_target(target: dict | None) -> str:
    if not target:
        return ""
    s, v = target.get("strategy"), target.get("value", "")
    if s == "role":
        return f'{v} "{target.get("name", "")}"' if target.get("name") else v
    return {"label": f'field "{v}"', "text": f'text "{v}"', "placeholder": f'placeholder "{v}"',
            "testid": f"test id {v}", "css": f"selector {v}"}.get(s, f"{s} {v}")


def default_description(action: str, target: dict | None, value: str | None, options: dict | None) -> str:
    spec = ACTIONS.get(action)
    if spec is None:
        return action
    t = describe_target(target)
    if action == "navigate":
        return f"Open {value}"
    if action == "fill":
        return f"Type \"{value}\" into {t}"
    if action == "api_request":
        o = options or {}
        return f"{o.get('method', 'GET')} {o.get('url', '')}"
    parts = [spec.label, t, f'"{value}"' if value and spec.value != "none" else ""]
    return " ".join(p for p in parts if p)
