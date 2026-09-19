"""
Shared helper utilities used across the application.

- Phone number masking (never show full numbers in UI or logs)
- Timezone conversion for display (Asia/Kolkata)
- Unsubscribe token generation
"""

import uuid
from datetime import datetime

import pytz


# The timezone used to display event dates/times to users
IST = pytz.timezone("Asia/Kolkata")


def mask_phone(phone: str) -> str:
    """
    Mask a phone number for display, e.g. '+919876543210' → '+91******3210'.

    Shows country code prefix and last 4 digits, masks the middle.
    """
    if not phone or len(phone) < 6:
        return "****"
    return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]


def generate_unsubscribe_token() -> str:
    """Generate a random, unguessable token for unsubscribe links."""
    return uuid.uuid4().hex


def now_ist() -> datetime:
    """Return the current time in Asia/Kolkata timezone."""
    return datetime.now(IST)


def format_event_datetime(event_date, event_time) -> str:
    """
    Format an event's date and time for display.

    Example: 'Saturday, 20 Sep 2026 at 3:00 PM IST'
    """
    if event_date is None:
        return "TBA"

    # Combine date and time for display
    date_str = event_date.strftime("%A, %d %b %Y")
    if event_time:
        time_str = event_time.strftime("%I:%M %p")
        return f"{date_str} at {time_str} IST"
    return date_str


def build_reminder_message(event) -> str:
    """
    Build the SMS reminder text for an event.

    Keeps it concise — SMS messages have a 160-character sweet spot.
    """
    parts = [f"Reminder: {event.title}"]

    if event.event_date:
        date_str = event.event_date.strftime("%d %b %Y")
        parts.append(date_str)

    if event.event_time:
        time_str = event.event_time.strftime("%I:%M %p")
        parts.append(time_str)

    if event.location:
        parts.append(event.location)

    parts.append(f"— {event.club_name}")

    return " | ".join(parts)
