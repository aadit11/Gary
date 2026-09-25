import json
from datetime import date, datetime

from core.speech import date_str, money_str, speak


def test_money_str():
    assert money_str(84.2) == "$84.20"
    assert money_str("1234.5") == "$1,234.50"


def test_date_str_date_only_has_no_time():
    assert date_str("2026-10-02") == "Friday, October 2"
    assert date_str(date(2026, 10, 2)) == "Friday, October 2"


def test_date_str_datetime():
    assert date_str(datetime(2026, 9, 25, 14, 0)) == "Friday, September 25 at 2 PM"
    assert date_str(datetime(2026, 9, 25, 9, 30)) == "Friday, September 25 at 9:30 AM"
    assert date_str("2026-09-25T00:15:00") == "Friday, September 25 at 12:15 AM"


def test_speak_shape():
    out = json.loads(speak("  Hi there. ", action_id="a1", data={"x": 1}))
    assert out == {"say": "Hi there.", "action_id": "a1", "data": {"x": 1}}
    assert json.loads(speak("Hi")) == {"say": "Hi"}
