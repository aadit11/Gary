"""MuseSparkAgent: turns a browser observation into a short plan of actions.

Prompt layout follows agisdk's example/hackable.py (goal, pruned accessibility tree, optional
screenshot, action space, annotated history, last error). The model answers with brief
reasoning and one fenced block containing one or more actions, one per line.
"""

from __future__ import annotations

import ast
import base64
import io
import logging
import re
from typing import Any, Callable

from agisdk.REAL.browsergym.utils.obs import flatten_axtree_to_str

from browser_agent.actions import ACTION_SET

log = logging.getLogger(__name__)

AXTREE_CHAR_CAP = 25_000
MAX_MISSES = 3
MAX_PLAN = 8

SYSTEM_TEXT = """# Instructions

You are operating a web browser to complete a task on behalf of an older adult who asked for it by phone. Review the goal, the current page, and your past actions, then produce the next actions. Your answer is executed by a program, so follow the format exactly.

Rules:
- Only choose items, restaurants, addresses, and options that actually appear on the page. Never invent them.
- If the goal names a specific item and it is not on the page, pick the closest match and say so in your final message.
- Follow the site's own flow to the end: the task is complete only after the final confirmation button (Place Order, Request, Book) has been clicked.
- Plan ahead: output several actions in one block when you are confident of them, one per line, in order. Use bid actions like click("12") only for elements in the current tree. For elements that will appear after an earlier action (a dialog's confirm button, the cart's Checkout button, the checkout page's Place Order button), use the named actions: click_named("button", "Checkout.*"), fill_named("textbox", "Search", "Souvla"), press_named("textbox", "Search", "Enter"). Name patterns are case-insensitive regexes; wildcard prices with .*
- If an action fails, you will be shown the page again and can re-plan from there.
- The tree may include elements that are off screen; you can act on them directly without scrolling. After the final confirmation click, reply DONE in the same plan; do not add waits.
- When the action is truly complete on the site, reply with exactly:
  send_msg_to_user("DONE: <one sentence saying exactly what was ordered or booked, from where, and the total or price shown>")
  It may be the last line of a plan whose earlier lines finish the flow.
- If the task cannot be done on this site, reply with report_infeasible("<short reason>").
- Think briefly, then give the plan in a single ``` fenced code block, one action per line.
"""

EXAMPLES = """Examples of answers:

I am on the store page and the item is visible. I will add it, confirm the dialog, open the cart, check out, and place the order.
```
click("92")
click_named("button", "Add to cart.*")
click_named("button", "^\\d+$")
click_named("button", "Checkout.*")
click_named("button", "^Place Order")
send_msg_to_user("DONE: Ordered one Classic Cheeseburger from Souvla for delivery, total $21.77.")
```

The order confirmation is showing, so the task is complete.
```
send_msg_to_user("DONE: Ordered one Classic Cheeseburger from Souvla for delivery, total $21.77.")
```"""


def element_info(obs: dict, bid: str) -> tuple[str, str]:
    """(role, name) for an element id from the accessibility tree, or ('', '')."""
    try:
        for node in obs["axtree_object"]["nodes"]:
            if str(node.get("browsergym_id", "")) == bid:
                role = (node.get("role") or {}).get("value", "")
                name = (node.get("name") or {}).get("value", "")
                return role, name
    except Exception:  # noqa: BLE001
        pass
    return "", ""


def describe_bid(obs: dict, bid: str) -> str:
    role, name = element_info(obs, bid)
    return f'{role} "{name[:60]}"'.strip() if role or name else ""


def action_bid(action: str) -> str | None:
    m = re.match(r'^\s*(?:click|fill|press|select_option|hover|dblclick|focus|clear)\(\s*["\']([^"\']+)["\']', action)
    return m.group(1) if m else None


def first_sentence(text: str) -> str:
    text = re.sub(r"```.*?```", "", text or "", flags=re.S).strip()
    return text.split("\n")[0][:160]


def flatten_pruned(obs: dict) -> str:
    """Visible, id-bearing elements only (DashDish home: 87k chars -> ~5k)."""
    ax = obs.get("axtree_object")
    if not ax:
        return ""
    ep = obs.get("extra_element_properties")
    text = ""
    # Prefer the whole page (offscreen elements included) when it is small enough: the model
    # then never needs to scroll. Fall back to visible-only for huge pages like the home page.
    for kw in (
        {"extra_properties": ep, "filter_with_bid_only": True},
        {"extra_properties": ep, "filter_visible_only": True, "filter_with_bid_only": True},
        {"extra_properties": ep, "filter_visible_only": True},
        {"extra_properties": ep},
        {},
    ):
        try:
            candidate = flatten_axtree_to_str(ax, **kw)
        except Exception:  # noqa: BLE001
            continue
        if not candidate.strip():
            continue
        text = candidate
        if len(text) <= AXTREE_CHAR_CAP:
            break
    if not text:
        return ""
    if len(text) > AXTREE_CHAR_CAP:
        text = text[:AXTREE_CHAR_CAP] + "\n... (tree truncated; scroll to see more)"
    return text


def screenshot_data_url(image: Any) -> str:
    from PIL import Image

    if not isinstance(image, Image.Image):
        image = Image.fromarray(image)
    if image.mode in ("RGBA", "LA"):
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


_FENCE = re.compile(r"```(?:[a-zA-Z]+[ \t]*\n)?(.*?)```", re.S)  # language tag only if on its own line
_TERMINAL = re.compile(r"^\s*(send_msg_to_user|report_infeasible)\((.*)\)\s*$", re.S)


def parse_plan(text: str) -> list[str]:
    """Actions in the last fenced block, one per line, comments and blanks dropped."""
    blocks = _FENCE.findall(text or "")
    if not blocks:
        return []
    out = []
    for line in blocks[-1].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
        if terminal_message(line):
            break
    return out[:MAX_PLAN]


def parse_action(text: str) -> str | None:
    plan = parse_plan(text)
    return plan[0] if plan else None


def terminal_message(action: str) -> tuple[str, str] | None:
    """('done'|'infeasible', text) if the action ends the episode, else None."""
    m = _TERMINAL.match(action or "")
    if not m:
        return None
    kind = "done" if m.group(1) == "send_msg_to_user" else "infeasible"
    raw = m.group(2).strip()
    try:
        text = ast.literal_eval(raw)
    except Exception:  # noqa: BLE001
        text = raw.strip("\"'")
    return kind, str(text)


class MuseSparkAgent:
    def __init__(self, goal: str, use_screenshot: bool = True, complete: Callable[..., str] | None = None):
        self.goal = goal
        self.use_screenshot = use_screenshot
        if complete is None:
            from browser_agent import muse

            complete = muse.complete
        self._complete = complete
        self.action_history: list[str] = []
        self.misses = 0
        self.model_calls = 0
        self.last_reply = ""

    def note(self, text: str) -> None:
        """Add a line to the history (e.g. replay progress, action errors)."""
        self.action_history.append(f"- {text}")

    def record(self, action: str, obs: dict | None, reason: str = "") -> None:
        bid = action_bid(action)
        desc = describe_bid(obs, bid) if (bid and obs) else ""
        entry = f"{len(self.action_history) + 1}. {action}"
        if desc:
            entry += f"   # on {desc}"
        if reason:
            entry += f"   # because: {reason}"
        self.action_history.append(entry)

    def build_messages(self, obs: dict) -> list[dict]:
        parts: list[dict] = [
            {"type": "text", "text": f"# Goal\n\n{self.goal}"},
            {"type": "text", "text": f"# Current page URL\n\n{obs.get('url', '')}"},
            {"type": "text", "text": f"# Current page Accessibility Tree (visible elements)\n\n{flatten_pruned(obs)}"},
        ]
        if self.use_screenshot and obs.get("screenshot") is not None:
            parts.append({"type": "text", "text": "# Current page Screenshot"})
            parts.append({"type": "image_url", "image_url": {"url": screenshot_data_url(obs["screenshot"]), "detail": "auto"}})
        parts.append({
            "type": "text",
            "text": "# Action Space\n\n" + ACTION_SET.describe(with_long_description=False, with_examples=True) + "\n\n" + EXAMPLES,
        })
        if self.action_history:
            parts.append({"type": "text", "text": "# History of past actions (oldest first)\n\n" + "\n".join(self.action_history[-20:])
                          + "\n\nDo not repeat an action that already succeeded. If the page did not change after an action, try a different element."})
        if obs.get("last_action_error"):
            parts.append({"type": "text", "text": f"# Error message from last action\n\n{str(obs['last_action_error'])[:600]}"})
        parts.append({
            "type": "text",
            "text": "# Next actions\n\nThink step by step about where you are in the flow and what remains, then give the plan in one fenced code block, one action per line.",
        })
        return [{"role": "system", "content": SYSTEM_TEXT}, {"role": "user", "content": parts}]

    def next_plan(self, obs: dict) -> list[str]:
        """One model call -> a list of actions (possibly ending with a terminal action)."""
        reply = self._complete(self.build_messages(obs))
        self.model_calls += 1
        self.last_reply = reply
        plan = parse_plan(reply)
        if not plan:
            self.misses += 1
            log.warning("no action in model reply (%d/%d): %s", self.misses, MAX_MISSES, reply[:200])
            if self.misses >= MAX_MISSES:
                return ['report_infeasible("I could not decide on a next step.")']
            return ["noop(500)"]
        self.misses = 0
        return plan

    def next_action(self, obs: dict) -> str:
        """Single-action interface (kept for tests and simple callers)."""
        plan = self.next_plan(obs)
        action = plan[0]
        self.record(action, obs, first_sentence(self.last_reply))
        return action
