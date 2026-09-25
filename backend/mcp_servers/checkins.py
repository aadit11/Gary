"""Vertical 1 (Person 1): get_daily_briefing, get_upcoming_appointments, confirm_reminder.

Phase 1 stub: one tool so the voice adapter has something to list and call. Person 1 replaces it.
"""

from mcp.server.fastmcp import FastMCP

from core.speech import speak

checkins = FastMCP("checkins", instructions="Daily check-ins, reminders, and the morning briefing.")


@checkins.tool()
def get_upcoming_appointments(user_id: str) -> str:
    """Tell the user about their next few appointments from the calendar."""
    return speak("I don't see any appointments on your calendar yet. I'll let you know when something comes up.")
