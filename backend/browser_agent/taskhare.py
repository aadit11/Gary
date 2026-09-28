"""Read TaskHare pages the way the browser agent sees them (accessibility text).

TaskHare has no API. The agent searches the site, and the results list is read straight from
the page's accessibility tree:

    [42] heading 'Plumbing'
    [43] list ''
        [44] listitem ''
            [45] heading 'Bay Plumbing Co.'
            [46] paragraph ''
                StaticText '4.8'
                StaticText 'stars · $'
                StaticText '120'
                StaticText 'visit · next'
                StaticText 'Monday, September 28 at 10 AM'
            [47] link 'Choose Bay Plumbing Co.', url='...'

The result is carried between jobs as one line the runner treats like any other DONE message:

    DONE: TASKERS [Plumbing]: Bay Plumbing Co. | $120 | Monday, September 28 at 10 AM || Rapid Rooter | $95 | ...
    DONE: TASKERS [Plumbing]: none
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

_HEADING = re.compile(r"^\s*\[\d+\]\s+heading\s+'(.*)'\s*$")
_LIST = re.compile(r"^\s*\[\d+\]\s+list\b")
_STATIC = re.compile(r"^\s*StaticText\s+'(.*)'\s*$")
_CHOOSE = re.compile(r"^\s*\[\d+\]\s+link\s+'Choose (.+?)'")
_DETAILS = re.compile(r"(\d+(?:\.\d+)?)\s*stars\s*·\s*\$\s*(\d+(?:\.\d+)?)\s*visit\s*·\s*next\s*(.+?)\s*$")
_RESULT = re.compile(r"TASKERS\s*(?:\[(?P<category>[^\]]*)\])?\s*:\s*(?P<body>.*)", re.I | re.S)


def parse_taskers(page_text: str) -> tuple[str, list[dict]]:
    """(category label, taskers) from a TaskHare results page. Each tasker: name, rating, price, time."""
    category = ""
    last_heading = ""
    taskers: list[dict] = []
    name = ""
    details: list[str] = []
    for line in (page_text or "").splitlines():
        m = _HEADING.match(line)
        if m:
            last_heading = m.group(1)
            name, details = last_heading, []
            continue
        if _LIST.match(line):
            category = category or last_heading
            continue
        m = _STATIC.match(line)
        if m and name:
            details.append(m.group(1))
            continue
        m = _CHOOSE.match(line)
        if m:
            chosen = m.group(1).strip()
            d = _DETAILS.search(" ".join(details))
            if d:
                taskers.append({
                    "name": chosen or name,
                    "rating": float(d.group(1)),
                    "price": float(d.group(2)),
                    "time": d.group(3).strip(" .'"),
                })
            name, details = "", []
    return category, taskers


def taskers_result_text(category: str, taskers: list[dict]) -> str:
    """The DONE line a search job finishes with; parse_taskers_result reads it back."""
    label = f" [{category}]" if category else ""
    if not taskers:
        return f"DONE: TASKERS{label}: none"
    parts = [f"{t['name']} | ${t['price']:g} | {t['time']}" for t in taskers]
    return f"DONE: TASKERS{label}: " + " || ".join(parts)


def parse_taskers_result(result_text: str) -> tuple[str, list[dict]] | None:
    """'DONE: TASKERS [Plumbing]: A | $120 | Monday ... || B | $95 | ...' -> ('Plumbing', [...]). None if not a TASKERS line."""
    m = _RESULT.search(result_text or "")
    if not m:
        return None
    category = (m.group("category") or "").strip()
    body = m.group("body").strip()
    taskers: list[dict] = []
    if body.lower().startswith("none"):
        return category, taskers
    for part in body.split("||"):
        fields = [f.strip() for f in part.split("|")]
        if len(fields) < 3 or not fields[0]:
            continue
        price = re.sub(r"[^\d.]", "", fields[1])
        try:
            taskers.append({"name": fields[0], "price": float(price), "time": fields[2].rstrip(" .")})
        except ValueError:
            continue
    return category, taskers


def slot_to_iso(label: str, now: datetime | None = None, tz: str = "") -> str | None:
    """'Monday, September 28 at 10 AM' -> '2026-09-28T10:00:00' (this year, or next if that date has already passed).
    With a timezone name the result carries its offset, e.g. '2026-09-28T10:00:00-04:00'."""
    now = now or datetime.now()
    text = (label or "").strip().rstrip(".")
    for fmt in ("%A, %B %d at %I:%M %p", "%A, %B %d at %I %p", "%B %d at %I:%M %p", "%B %d at %I %p"):
        for year in (now.year, now.year + 1):
            try:
                when = datetime.strptime(f"{text} {year}", fmt + " %Y")
            except ValueError:
                continue
            if (now - when).days > 1:  # slots are upcoming; a date well in the past means next year
                continue
            if tz:
                try:
                    return when.replace(tzinfo=ZoneInfo(tz)).isoformat()
                except Exception:  # noqa: BLE001
                    pass
            return when.strftime("%Y-%m-%dT%H:%M:%S")
    return None
