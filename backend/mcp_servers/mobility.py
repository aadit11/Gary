"""Vertical 4 (Person 4): prepare_ride, confirm_ride, get_ride_status, suggest_ride_for_appointment.

Phase 1 stub: one tool so the voice adapter has something to list and call. Person 4 replaces it.
"""

from mcp.server.fastmcp import FastMCP

from core.speech import speak

mobility = FastMCP("mobility", instructions="Ride booking and ride status.")


@mobility.tool()
def get_ride_status(user_id: str) -> str:
    """Tell the user where their booked ride is when they ask about their ride."""
    return speak("You don't have a ride booked right now. Would you like me to book one?")
