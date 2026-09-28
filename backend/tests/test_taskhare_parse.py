from datetime import datetime

from browser_agent.taskhare import parse_taskers, parse_taskers_result, slot_to_iso, taskers_result_text

PAGE = """[24] main ''
\t[29] form ''
\t\t[32] textbox 'Describe the job' value='my sink is leaking'
\t\t[33] button 'Search'
\t[34] navigation 'Job types'
\t\t[35] link 'Plumbing', url='http://127.0.0.1:3000/taskhare?q=Plumbing'
\t[42] heading 'Plumbing'
\t[43] list ''
\t\t[44] listitem ''
\t\t\t[45] heading 'Bay Plumbing Co.'
\t\t\t[46] paragraph ''
\t\t\t\tStaticText '4.8'
\t\t\t\tStaticText 'stars · $'
\t\t\t\tStaticText '120'
\t\t\t\tStaticText 'visit · next'
\t\t\t\tStaticText 'Monday, September 28 at 10 AM'
\t\t\t[47] link 'Choose Bay Plumbing Co.', url='http://127.0.0.1:3000/taskhare/hire/p1?q=my%20sink'
\t\t[52] listitem ''
\t\t\t[53] heading 'Rapid Rooter'
\t\t\t[54] paragraph ''
\t\t\t\tStaticText '4.5'
\t\t\t\tStaticText 'stars · $'
\t\t\t\tStaticText '95'
\t\t\t\tStaticText 'visit · next'
\t\t\t\tStaticText 'Monday, September 28 at 4 PM'
\t\t\t[55] link 'Choose Rapid Rooter', url='http://127.0.0.1:3000/taskhare/hire/p2?q=my%20sink'
"""


def test_parse_taskers_reads_results_page():
    category, taskers = parse_taskers(PAGE)
    assert category == "Plumbing"
    assert [t["name"] for t in taskers] == ["Bay Plumbing Co.", "Rapid Rooter"]
    assert taskers[0]["price"] == 120 and taskers[0]["rating"] == 4.8
    assert taskers[0]["time"] == "Monday, September 28 at 10 AM"
    assert taskers[1]["time"] == "Monday, September 28 at 4 PM"


def test_parse_taskers_empty_page():
    category, taskers = parse_taskers("[42] heading 'Plumbing'\n[43] paragraph ''\n\tStaticText 'No taskers for that yet.'")
    assert taskers == []


def test_result_text_round_trips():
    category, taskers = parse_taskers(PAGE)
    text = taskers_result_text(category, taskers)
    assert text.startswith("DONE: TASKERS [Plumbing]: Bay Plumbing Co. | $120 | Monday, September 28 at 10 AM || Rapid Rooter")
    back = parse_taskers_result(text)
    assert back is not None
    assert back[0] == "Plumbing"
    assert [(t["name"], t["price"], t["time"]) for t in back[1]] == [(t["name"], t["price"], t["time"]) for t in taskers]


def test_result_text_none_and_non_matching():
    assert parse_taskers_result("DONE: TASKERS [Plumbing]: none") == ("Plumbing", [])
    assert parse_taskers_result("TASKERS: A | 80 | Tuesday, September 29 at 9 AM") == ("", [{"name": "A", "price": 80.0, "time": "Tuesday, September 29 at 9 AM"}])
    assert parse_taskers_result("DONE: OPEN. Souvla can take a delivery order.") is None


def test_slot_to_iso():
    now = datetime(2026, 9, 27, 12, 0)
    assert slot_to_iso("Monday, September 28 at 10 AM", now) == "2026-09-28T10:00:00"
    assert slot_to_iso("Tuesday, September 29 at 1 PM", now) == "2026-09-29T13:00:00"
    assert slot_to_iso("Monday, September 28 at 10:30 AM", now) == "2026-09-28T10:30:00"
    assert slot_to_iso("Monday, January 5 at 9 AM", now) == "2027-01-05T09:00:00"
    assert slot_to_iso("sometime next week", now) is None
    assert slot_to_iso("Monday, September 28 at 4 PM", now, tz="America/New_York") == "2026-09-28T16:00:00-04:00"
    assert slot_to_iso("Monday, September 28 at 4 PM", now, tz="Not/AZone") == "2026-09-28T16:00:00"
