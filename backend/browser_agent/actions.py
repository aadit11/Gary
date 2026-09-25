"""Action set for the browser agent: the SDK's bid-based actions plus name-based ones.

Name-based actions (click_named, fill_named, press_named) find an element by ARIA role and a
regex on its accessible name, waiting up to 5 s for it to appear. They let the model plan
actions on elements that are not on the page yet, and they are what learned flows replay.
These functions are inlined into the SDK's execution context, so they must be self-contained
and may only use the `page` global.
"""

from __future__ import annotations

from agisdk.REAL.browsergym.core.action.highlevel import HighLevelActionSet

NAMED_TIMEOUT_MS = 8000


def click_named(role: str, name_pattern: str):
    """Click the first visible element with this ARIA role whose accessible name matches the regex (case-insensitive). Use it for elements that will appear after an earlier action.

    Examples:
        click_named("button", "Checkout.*")
        click_named("button", "^Place Order")
    """
    import re

    rx = re.compile(name_pattern, re.I)
    loc = page.get_by_role(role, name=rx).first  # noqa: F821
    try:
        loc.wait_for(state="visible", timeout=8000)
    except Exception:
        # Fall back to any element whose text matches (e.g. a card whose image/heading was clicked).
        plain = re.sub(r"^(image|img)\\?\s+", "", name_pattern, flags=re.I)
        loc = page.get_by_text(re.compile(plain, re.I)).first  # noqa: F821
        loc.wait_for(state="visible", timeout=4000)
    loc.click()


def fill_named(role: str, name_pattern: str, value: str):
    """Fill the first visible textbox/combobox with this role whose accessible name matches the regex.

    Examples:
        fill_named("textbox", "Search", "Souvla")
    """
    import re

    loc = page.get_by_role(role, name=re.compile(name_pattern, re.I)).first  # noqa: F821
    loc.wait_for(state="visible", timeout=8000)
    loc.fill(value)


def press_named(role: str, name_pattern: str, key: str):
    """Press a key inside the first visible element with this role whose accessible name matches the regex.

    Examples:
        press_named("textbox", "Search", "Enter")
    """
    import re

    loc = page.get_by_role(role, name=re.compile(name_pattern, re.I)).first  # noqa: F821
    loc.wait_for(state="visible", timeout=8000)
    loc.press(key)


ACTION_SET = HighLevelActionSet(
    subsets=["chat", "bid", "nav", "infeas", "custom"],
    custom_actions=[click_named, fill_named, press_named],
    strict=False,
    multiaction=False,  # the runner executes plans one action at a time so it can detect failures
)
