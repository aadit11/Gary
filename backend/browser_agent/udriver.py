"""Read the Udriver clone's trip page the way the browser agent sees it (accessibility text).

Once a driver is assigned the page reads, in order:

    [329] heading 'Heading to Pacific Cafe'
    [330] button '8:12 PM'
    [345] heading 'Alvaro'            <- driver
    [346] heading '9L13XK'            <- plate
    [347] heading 'Toyota Prius'      <- car
    [350] heading '4.99'              <- rating
    [370] image 'PickUp Location'
    [373] heading 'Fitness Urbano'
    [374] heading '80 Missouri Street, San Francisco'
    [376] image 'search'
    [379] heading 'Pacific Cafe'
    [380] heading '7000 Geary Boulevard, San Francisco'
    [385] heading '$ 13.30'
"""

from __future__ import annotations

import re

_HEADING = re.compile(r"^\s*\[\d+\]\s+heading\s+'(.*)'\s*$")
_IMAGE = re.compile(r"^\s*\[\d+\]\s+image\s+'([^']*)'")
_BUTTON = re.compile(r"^\s*\[\d+\]\s+button\s+'(.*)'\s*$")
_PRICE = re.compile(r"^\$\s*([\d,]+(?:\.\d+)?)$")
_CLOCK = re.compile(r"^\d{1,2}:\d{2} [AP]M$")


def parse_trip(page_text: str) -> dict:
    """Driver, plate, car, rating, pickup, dropoff, and price from a Udriver trip page; blanks when absent."""
    out = {"dropoff": "", "driver": "", "plate": "", "car": "", "rating": "", "pickup": "", "pickup_address": "",
           "dropoff_address": "", "price": 0.0, "eta_label": ""}
    lines = (page_text or "").splitlines()
    headings: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        m = _HEADING.match(line)
        if m:
            headings.append((idx, m.group(1).strip()))
    for k, (_, text) in enumerate(headings):
        m = re.match(r"Heading to (.+)", text)
        if m:
            out["dropoff"] = m.group(1).strip()
            after = [t for _, t in headings[k + 1:k + 5]]
            if len(after) >= 3:
                out["driver"], out["plate"], out["car"] = after[0], after[1], after[2]
            if len(after) >= 4 and re.fullmatch(r"\d(?:\.\d+)?", after[3]):
                out["rating"] = after[3]
            break
    for idx, line in enumerate(lines):
        m = _IMAGE.match(line)
        if not m or m.group(1) not in ("PickUp Location", "search"):
            continue
        following = [t for j, t in headings if j > idx][:2]
        if len(following) < 2:
            continue
        if m.group(1) == "PickUp Location":
            out["pickup"], out["pickup_address"] = following
        else:
            out["dropoff"] = out["dropoff"] or following[0]
            out["dropoff_address"] = following[1]
    for _, text in headings:
        m = _PRICE.match(text)
        if m:
            out["price"] = float(m.group(1).replace(",", ""))
            break
    for line in lines:
        m = _BUTTON.match(line)
        if m and _CLOCK.match(m.group(1).strip()):
            out["eta_label"] = m.group(1).strip()
            break
    return out


def trip_booked(trip: dict) -> bool:
    return bool(trip.get("driver") and trip.get("plate"))


def spoken_plate(plate: str) -> str:
    """'9L13XK' -> '9 L 1 3 X K' so the plate is read out one character at a time."""
    return " ".join((plate or "").upper())
