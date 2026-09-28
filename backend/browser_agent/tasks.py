"""A REAL clone task with a free-form goal (not one of the benchmark tasks).

Reuses the SDK's task plumbing (site URL, state reset via /config and /finish) from the
`<site>-1` benchmark entry, then overrides the goal. No benchmark evaluation runs; the runner
decides completion from the agent's DONE message.
"""

from __future__ import annotations

from agisdk.REAL.browsergym.webclones.base import AbstractWebCloneTask

from config import settings

SITES = ("dashdish", "udriver", "taskhare")
LOCAL_SITES = {"taskhare"}

# Short, site-specific flow hints appended to the goal: the knowledge a person who has used the
# app once would have. Describe the flow, never specific element ids.
SITE_HINTS = {
    "dashdish": (
        "How DashDish works: use the search box at the top to find the restaurant and open its page by "
        "clicking its heading or link (prefer headings, links, and buttons over images). Click the Add button "
        "next to the item you want; a dialog appears with size options and an 'Add to cart' button, click that. "
        "Then open the cart: it is the button at the top right whose label is just the item count (pattern ^\\d+$). "
        "Click Checkout in the cart drawer, and on the checkout page click Place Order. The order is complete "
        "only after Place Order has been clicked and a confirmation is shown."
    ),
    "udriver": (
        "How Udriver works: type the pickup place in 'Enter Location' and pick a suggestion from the list, "
        "type the destination in 'Enter Destination' and pick a suggestion, click 'See prices', wait for the "
        "ride options to load, then click the Request button for the chosen ride. The ride is booked only "
        "after the Request button has been clicked and a confirmation is shown."
    ),
    "taskhare": (
        "How TaskHare works: type the job in the box labeled Describe the job and click Search, "
        "or click a job type such as Plumbing. Click the link Choose and the tasker's name. "
        "Click the time that matches the visit, then click Confirm this visit. "
        "The hire is complete only when the page heading says You're booked. Do not invent a tasker or a time."
    ),
}

TASKHARE_SEARCH_HINT = (
    "How to search TaskHare: type the job in the box labeled Describe the job and press Enter or click Search, "
    "or click a job type such as Plumbing. The results list each tasker with a price and their next available time. "
    "This is a search only: do not click Choose, do not pick a time, and do not confirm anything."
)

TASKHARE_STAY_HINT = (
    "You are already on the TaskHare results list for this job. Do not search again. "
    "Click the link Choose and the tasker's name, click the time that matches the visit, then click Confirm this visit. "
    "The hire is complete only when the page heading says You're booked. Do not invent a tasker or a time."
)


LOOKUP_HINT = (
    "How to look a restaurant up on DashDish: use the search box at the top, open the restaurant by its "
    "heading or link, and read whether it is open, closed, or not listed. Do not add items, open the cart, or place an order."
)

STAY_HINT = (
    "You are already on the restaurant page. Do not go back to the home page and do not search for the restaurant again. "
    "Find the dish on this menu, or the closest item to it if the exact name is not listed (say which one you chose). "
    "The menu items are in the page tree; do not scroll around looking. Click the Add button next to it; a dialog appears with size options and an "
    "'Add to cart' button, click that. Then open the cart: it is the button at the top right whose label is just the "
    "item count (pattern ^\\d+$). Click Checkout in the cart drawer, and on the checkout page click Place Order. "
    "The order is complete only after Place Order has been clicked and a confirmation is shown."
)


LOOKUP_HINTS = {"dashdish": LOOKUP_HINT, "taskhare": TASKHARE_SEARCH_HINT}
STAY_HINTS = {"dashdish": STAY_HINT, "taskhare": TASKHARE_STAY_HINT}


def goal_with_hints(site: str, goal: str, lookup: bool = False, stay: bool = False) -> str:
    if lookup:
        hint = LOOKUP_HINTS.get(site, SITE_HINTS.get(site, ""))
    elif stay:
        hint = STAY_HINTS.get(site, SITE_HINTS.get(site, ""))
    else:
        hint = SITE_HINTS.get(site, "")
    return goal + "\n\n" + hint if hint else goal


def resume_goal(site: str, page_name: str, goal: str) -> str:
    """The goal for a job that continues on a page an earlier lookup parked."""
    if site == "taskhare":
        name = page_name or "this job"
        return (
            f"You are already on the TaskHare results for {name}. Stay on this page and do not search again. "
            f"The request was: {goal}"
        )
    name = page_name or "the restaurant"
    return (
        f"You are already on the {name} page. Stay on this page. "
        "Do not go back to the home page and do not search for the restaurant again. "
        f"Find the dish on this menu and place the delivery order. The request was: {goal}"
    )


def _task_version(site: str) -> str:
    """The SDK ships some clones only as v1 tasks (Udriver); prefer v2 when it exists."""
    try:
        from agisdk.REAL.browsergym.webclones.task_config import TASKS_BY_VERSION

        return "v2" if f"{site}-1" in TASKS_BY_VERSION.get("v2", []) else "v1"
    except Exception:  # noqa: BLE001
        return "v2"


def site_url(site: str) -> str:
    return {
        "dashdish": settings.real_dashdish_url,
        "udriver": settings.real_udriver_url,
        "taskhare": settings.taskhare_url,
    }[site].rstrip("/")


class FreeformCloneTask(AbstractWebCloneTask):
    task_id = "freeform"

    def __init__(self, seed: int, site: str = "dashdish", goal: str = "", url: str | None = None) -> None:
        if site not in SITES:
            raise ValueError(f"unknown site {site!r}; expected one of {SITES}")
        self.local = site in LOCAL_SITES
        if self.local:
            from agisdk.REAL.browsergym.core.task import AbstractBrowserTask

            AbstractBrowserTask.__init__(self, seed)
            self.slow_mo = 0
            self.timeout = 15000
        else:
            super().__init__(seed, task_name=f"{site}-1", task_version=_task_version(site))
        self.site = site
        self.goal = goal
        self.url = (url or site_url(site)).rstrip("/")
        self.page = None
        self.background_page = None

    def setup(self, page):  # noqa: ANN001
        if self.local:
            self.page = page
            page.goto(self.url, timeout=20000)
            return self.goal, {}
        return super().setup(page)

    def teardown(self) -> None:
        if self.local or self.background_page is None:
            return
        super().teardown()

    def validate(self, page, chat_messages, timeout: int = 1000, verbose: bool = True):  # noqa: ARG002
        return 0.0, False, "", {}
