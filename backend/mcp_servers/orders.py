"""Vertical 3 (Person 3): get_favorite_orders, search_food_and_groceries, prepare_order, confirm_order,
find_home_service, prepare_service_booking, confirm_service_booking.

Phase 1 stub: one tool so the voice adapter has something to list and call. Person 3 replaces it.
"""

from mcp.server.fastmcp import FastMCP

from core.speech import speak

orders = FastMCP("orders", instructions="Food and grocery orders, and home service bookings.")


@orders.tool()
def get_favorite_orders(user_id: str) -> str:
    """List the user's saved usual orders when they ask to order their usual."""
    return speak("I don't have any usual orders saved for you yet. Tell me what you'd like and I can save it.")
