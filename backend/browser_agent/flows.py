"""Learned flows: after a successful job, the executed actions are saved keyed by element role
and name (never by element id) so the next run with the same flow key can replay them without
the model, falling back to the model at the first step that does not match the live page.

Stored as JSON under backend/data/flows/<site>/<key>.json.
"""

from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path
from typing import Any

FLOWS_DIR = Path(__file__).resolve().parent.parent / "data" / "flows"
_NUMBER = re.compile(r"[$€£]?\d[\d,]*(?:\.\d+)?")


def name_pattern(name: str) -> str:
    """Regex for an accessible name with numbers/prices wildcarded: 'Checkout $19.10' -> 'Checkout .*'."""
    name = (name or "").strip()
    if not name:
        return ""
    placeholder = "\x00"
    masked = _NUMBER.sub(placeholder, name)
    escaped = re.escape(masked).replace(re.escape(placeholder), ".*")
    return escaped


def _args(action: str) -> tuple[str, list[Any]]:
    m = re.match(r"^\s*(\w+)\s*\((.*)\)\s*$", action, re.S)
    if not m:
        return "", []
    try:
        node = ast.parse(f"f({m.group(2)})", mode="eval").body
        return m.group(1), [ast.literal_eval(a) for a in node.args]
    except Exception:  # noqa: BLE001
        return m.group(1), []


def to_named_step(action: str, role: str, name: str) -> dict | None:
    """Convert an executed action into a replayable, name-keyed step. None if it can't be."""
    fn, args = _args(action)
    if fn in ("noop", "send_msg_to_user", "report_infeasible", "scroll", "go_back", "go_forward", "goto"):
        return {"action": fn, "args": args} if fn in ("scroll", "go_back", "goto") else None
    if fn in ("click_named", "fill_named", "press_named"):
        step = {"action": fn[:-6], "role": args[0], "name": args[1]}
        if fn == "fill_named":
            step["value"] = args[2]
        if fn == "press_named":
            step["key"] = args[2]
        return step
    if fn not in ("click", "fill", "press", "select_option"):
        return None
    pat = name_pattern(name)
    if not role or not pat:
        return None
    step: dict[str, Any] = {"action": fn, "role": role, "name": pat}
    if fn == "fill":
        step["value"] = args[1] if len(args) > 1 else ""
    elif fn == "press":
        step["key"] = args[1] if len(args) > 1 else "Enter"
    elif fn == "select_option":
        step["value"] = args[1] if len(args) > 1 else ""
        step["action"] = "select"
    return step


def step_to_action(step: dict) -> str:
    a = step["action"]
    if a == "scroll":
        return f"scroll({step['args'][0]}, {step['args'][1]})"
    if a == "go_back":
        return "go_back()"
    if a == "goto":
        return f"goto({step['args'][0]!r})"
    role, name = step["role"], step["name"]
    if a == "click":
        return f"click_named({role!r}, {name!r})"
    if a == "fill":
        return f"fill_named({role!r}, {name!r}, {step.get('value', '')!r})"
    if a == "press":
        return f"press_named({role!r}, {name!r}, {step.get('key', 'Enter')!r})"
    if a == "select":
        return f"fill_named({role!r}, {name!r}, {step.get('value', '')!r})"
    raise ValueError(f"unknown step {a}")


class FlowStore:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else FLOWS_DIR

    def path(self, site: str, key: str) -> Path:
        safe = re.sub(r"[^a-z0-9_-]+", "-", key.lower()).strip("-") or "flow"
        return self.root / site / f"{safe}.json"

    def load(self, site: str, key: str) -> dict | None:
        p = self.path(site, key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            return None

    def save(self, site: str, key: str, goal: str, steps: list[dict], result_text: str) -> Path:
        p = self.path(site, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"site": site, "key": key, "goal": goal, "steps": steps, "result_text": result_text,
                                 "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
        return p


def _path(url: str) -> str:
    return re.sub(r"[?#].*$", "", url or "").rstrip("/")


def compress_executed(executed: list[dict]) -> tuple[list[dict], bool]:
    """Turn a job's executed actions into a replayable flow.

    * failed steps, scrolls, and noops are dropped;
    * the navigation prefix (everything up to the last page change before the first button
      click) collapses into one goto(url), so a replay opens the store page directly.
    Returns (steps, complete); complete is False if a needed step could not be named.
    """
    ok_steps = [e for e in executed if e.get("ok")]
    first_button = next((i for i, e in enumerate(ok_steps) if (e.get("role") or "").lower() == "button"), None)
    goto_url = None
    cut = 0
    if first_button:
        for i in range(first_button - 1, -1, -1):
            e = ok_steps[i]
            if e.get("url_after") and _path(e["url_after"]) != _path(e.get("url_before", "")):
                goto_url = e["url_after"]
                cut = i + 1
                break
    steps: list[dict] = []
    complete = True
    if goto_url:
        steps.append({"action": "goto", "args": [goto_url]})
    for e in ok_steps[cut:]:
        fn = e["action"].split("(")[0].strip()
        if fn in ("noop", "scroll", "send_msg_to_user", "report_infeasible"):
            continue
        st = to_named_step(e["action"], e.get("role", ""), e.get("name", ""))
        if st is None:
            complete = False
            continue
        steps.append(st)
    return steps, complete
