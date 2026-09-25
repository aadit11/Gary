"""MuseSparkAgent: turns a browser observation into the next action string.

Prompt layout follows agisdk's example/hackable.py (goal, accessibility tree, optional screenshot,
action space, history, last error). The model answers with brief reasoning and exactly one action
inside a ``` fenced block, e.g. ```click("12")```.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from typing import Any, Callable

from agisdk.REAL.browsergym.core.action.highlevel import HighLevelActionSet
from agisdk.REAL.browsergym.utils.obs import flatten_axtree_to_str

log = logging.getLogger(__name__)

ACTION_SET = HighLevelActionSet(subsets=["chat", "bid", "infeas"], strict=False, multiaction=False)
AXTREE_CHAR_CAP = 80_000
MAX_MISSES = 3

SYSTEM_TEXT = """# Instructions

You are operating a web browser to complete a task on behalf of an older adult who asked for it by phone. Review the goal, the current page, and your past actions, then choose the single best next action. Your answer is executed by a program, so follow the format exactly.

Rules:
- Only choose items, restaurants, addresses, and options that actually appear on the page. Never invent them.
- If the goal names a specific item and it is not on the page, pick the closest match and say so in your final message.
- Use the site's own flow: open the store or search, add items, open the cart, go to checkout, place the order (or request the ride). Do not stop before the final confirmation button has been clicked.
- Keep going until the action is truly complete on the site. Then, and only then, reply with:
  send_msg_to_user("DONE: <one sentence saying exactly what was ordered or booked, from where, and the total or price shown>")
- If the task cannot be done on this site, reply with report_infeasible("<short reason>").
- Think briefly, then output exactly one action in a ``` fenced code block on its own line.
"""


def describe_bid(obs: dict, bid: str) -> str:
    """'role "name"' for an element id from the accessibility tree, or ''."""
    try:
        for node in obs["axtree_object"]["nodes"]:
            if str(node.get("browsergym_id", "")) == bid:
                role = (node.get("role") or {}).get("value", "")
                name = (node.get("name") or {}).get("value", "")
                return f'{role} "{name[:60]}"'.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def first_sentence(text: str) -> str:
    text = re.sub(r"```.*?```", "", text or "", flags=re.S).strip()
    return text.split("\n")[0][:160]


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


def parse_action(text: str) -> str | None:
    """Last fenced block, first non-empty line inside it."""
    blocks = _FENCE.findall(text or "")
    if not blocks:
        return None
    for line in reversed([l.strip() for l in blocks[-1].splitlines() if l.strip()]):
        return line
    return None


def terminal_message(action: str) -> tuple[str, str] | None:
    """('done'|'infeasible', text) if the action ends the episode, else None."""
    m = _TERMINAL.match(action or "")
    if not m:
        return None
    kind = "done" if m.group(1) == "send_msg_to_user" else "infeasible"
    raw = m.group(2).strip()
    try:
        import ast

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
        self.last_reply = ""

    def build_messages(self, obs: dict) -> list[dict]:
        axtree = ""
        try:
            axtree = flatten_axtree_to_str(obs["axtree_object"], extra_properties=obs.get("extra_element_properties"))
        except Exception:  # noqa: BLE001
            try:
                axtree = flatten_axtree_to_str(obs["axtree_object"])
            except Exception:  # noqa: BLE001
                log.exception("axtree flatten failed")
        if len(axtree) > AXTREE_CHAR_CAP:
            axtree = axtree[:AXTREE_CHAR_CAP] + "\n... (tree truncated; scroll to see more)"

        parts: list[dict] = [
            {"type": "text", "text": f"# Goal\n\n{self.goal}"},
            {"type": "text", "text": f"# Current page URL\n\n{obs.get('url', '')}"},
            {"type": "text", "text": f"# Current page Accessibility Tree\n\n{axtree}"},
        ]
        if self.use_screenshot and obs.get("screenshot") is not None:
            parts.append({"type": "text", "text": "# Current page Screenshot"})
            parts.append({"type": "image_url", "image_url": {"url": screenshot_data_url(obs["screenshot"]), "detail": "auto"}})
        parts.append({
            "type": "text",
            "text": "# Action Space\n\n"
            + ACTION_SET.describe(with_long_description=False, with_examples=True)
            + "\n\nExamples of answers:\n\nThe Add button for the cheeseburger has bid 92, so I will click it.\n```click(\"92\")```\n\n"
            "The order confirmation is showing, so the task is complete.\n```send_msg_to_user(\"DONE: Ordered one Classic Cheeseburger from Souvla for delivery, total $18.10.\")```",
        })
        if self.action_history:
            parts.append({"type": "text", "text": "# History of past actions (oldest first)\n\n" + "\n".join(self.action_history[-15:]) + "\n\nDo not repeat an action that already succeeded. If the page did not change after an action, try a different element."})
        if obs.get("last_action_error"):
            parts.append({"type": "text", "text": f"# Error message from last action\n\n{obs['last_action_error']}"})
        parts.append({
            "type": "text",
            "text": "# Next action\n\nThink step by step about where you are in the flow and what remains, then give exactly one action in a fenced code block.",
        })
        return [{"role": "system", "content": SYSTEM_TEXT}, {"role": "user", "content": parts}]

    def next_action(self, obs: dict) -> str:
        reply = self._complete(self.build_messages(obs))
        self.last_reply = reply
        action = parse_action(reply)
        if action is None:
            self.misses += 1
            log.warning("no action in model reply (%d/%d): %s", self.misses, MAX_MISSES, reply[:200])
            if self.misses >= MAX_MISSES:
                return 'report_infeasible("I could not decide on a next step.")'
            return "noop(500)"
        self.misses = 0
        bid = re.search(r'\(\s*["\']([^"\']+)["\']', action)
        desc = describe_bid(obs, bid.group(1)) if bid else ""
        note = first_sentence(reply)
        entry = f"{len(self.action_history) + 1}. {action}"
        if desc:
            entry += f"   # on {desc}"
        if note:
            entry += f"   # because: {note}"
        self.action_history.append(entry)
        return action
