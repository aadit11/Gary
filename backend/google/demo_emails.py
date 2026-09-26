"""Demo mailbox contents for seed_gmail.py. Bodies are crafted to match ingestion heuristics
and core.policy.SCAM_PATTERNS so classify() stays deterministic for the hackathon demo.
"""

from __future__ import annotations

from typing import Any

# Sender addresses look plausible; they are not real services.
DEMO_EMAILS: list[dict[str, Any]] = [
    {
        "key": "bill_electric",
        "classification": "bill",
        "sender": "billing@cityelectric.example",
        "subject": "Your City Electric bill is ready",
        "body": (
            "Dear Margaret,\n\n"
            "Your City Electric bill for this month is ready.\n"
            "Amount due: $84.20\n"
            "Due by: October 2, 2026\n\n"
            "Thank you for being a City Electric customer.\n"
        ),
    },
    {
        "key": "bill_pharmacy",
        "classification": "bill",
        "sender": "billing@sunrisepharmacy.example",
        "subject": "Sunrise Pharmacy — balance due",
        "body": (
            "Hello Margaret Chen,\n\n"
            "Sunrise Pharmacy has a balance due for your recent prescription.\n"
            "Amount due: $23.50\n"
            "Due by: October 5, 2026\n\n"
            "You can pay by phone or in the store.\n"
        ),
    },
    {
        "key": "bill_water",
        "classification": "bill",
        "sender": "noreply@springfieldwater.example",
        "subject": "Springfield Water bill notice",
        "body": (
            "Springfield Water Department\n\n"
            "Amount due: $41.15\n"
            "Due by: October 8, 2026\n\n"
            "Please pay your Springfield Water bill by the due date.\n"
        ),
    },
    {
        "key": "pharmacy_notice",
        "classification": "appointment",
        "sender": "refills@sunrisepharmacy.example",
        "subject": "Your prescription is ready for pickup",
        "body": (
            "Sunrise Pharmacy\n\n"
            "Your prescription refill is ready for pickup.\n"
            "Please see the pharmacist on Friday, September 26, 2026 at 11 AM.\n"
            "Location: Sunrise Pharmacy, 100 Main Street.\n"
        ),
    },
    {
        "key": "doctor_appointment",
        "classification": "appointment",
        "sender": "appointments@springfieldmedical.example",
        "subject": "Appointment reminder — Dr. Patel",
        "body": (
            "Springfield Medical Clinic\n\n"
            "This is a reminder of your doctor's appointment with Dr. Patel.\n"
            "When: Saturday, September 26, 2026 at 2:00 PM\n"
            "Location: Springfield Medical, 200 Oak Avenue\n\n"
            "Please arrive 10 minutes early.\n"
        ),
    },
    {
        "key": "scam_medicare",
        "classification": "scam",
        "sender": "alerts@medicare-verify.example",
        "subject": "URGENT: Your Medicare will be suspended",
        "body": (
            "Your Medicare benefits will be suspended unless you verify your account today.\n"
            "Call us immediately to keep your coverage active.\n"
            "This is an automated Medicare security alert.\n"
        ),
    },
    {
        "key": "scam_package",
        "classification": "scam",
        "sender": "customs@parcel-fees.example",
        "subject": "Unpaid package customs fee — action required",
        "body": (
            "Your package is being held for an unpaid customs fee.\n"
            "Pay the delivery fee now or your parcel will be returned.\n"
            "Click below to complete redelivery payment.\n"
        ),
    },
    {
        "key": "scam_grandchild",
        "classification": "scam",
        "sender": "help@family-urgent.example",
        "subject": "Grandma please help — grandson in trouble",
        "body": (
            "Hi Grandma, this is your grandson. I was in a car accident and I am in jail.\n"
            "I need bail money right away. Please do not tell Mom. Wire transfer or gift cards work.\n"
            "Please hurry, I am in serious trouble.\n"
        ),
    },
    {
        "key": "other_newsletter",
        "classification": "other",
        "sender": "hello@springfieldgardenclub.example",
        "subject": "Springfield Garden Club weekly newsletter",
        "body": (
            "This week's garden tips: water early in the morning and deadhead your roses.\n"
            "Our next potluck is next month. Hope to see you there!\n"
        ),
    },
]

# Calendar event created alongside the doctor appointment email (seed_gmail.py).
DOCTOR_EVENT = {
    "summary": "Dr. Patel appointment",
    "location": "Springfield Medical, 200 Oak Avenue",
    "description": "Seeded by Gary seed_gmail.py for the morning briefing demo.",
    # Local America/New_York wall time; seed script converts with the user's timezone.
    "start_hour": 14,
    "start_minute": 0,
    "duration_minutes": 45,
}
