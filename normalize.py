"""
Shared normalization logic for Tripleseat events and bookings.
Used by dashboard.py, api/events.py, and calendar_builder.py.
"""


def normalize(raw, kind="event"):
    """Normalize a raw Tripleseat record into a flat dict.

    Args:
        raw: Raw dict from the Tripleseat API (may be nested under the kind key).
        kind: "event" or "booking".

    Returns:
        Flat dict with consistent keys: id, type, name, status, start, end,
        location, room, contact, guest_count, description.
    """
    r = raw.get(kind, raw)
    if kind == "event":
        return {
            "id": r.get("id"),
            "type": "event",
            "name": r.get("name") or r.get("event_name") or "Untitled Event",
            "status": (r.get("status") or r.get("event_status") or "").lower(),
            "start": r.get("event_start") or r.get("start_date") or r.get("event_date") or "",
            "end": r.get("event_end") or r.get("end_date") or "",
            "location": r.get("location_name") or r.get("location") or "",
            "room": r.get("room_name") or r.get("room") or "",
            "contact": r.get("contact_name") or "",
            "guest_count": r.get("guest_count") or r.get("guests") or 0,
            "description": r.get("description") or "",
        }
    else:
        return {
            "id": r.get("id"),
            "type": "booking",
            "name": r.get("name") or r.get("booking_name") or "Untitled Booking",
            "status": (r.get("status") or r.get("booking_status") or "").lower(),
            "start": r.get("start") or r.get("start_date") or r.get("booking_start") or "",
            "end": r.get("end") or r.get("end_date") or r.get("booking_end") or "",
            "location": r.get("location_name") or r.get("location") or "",
            "room": r.get("room_name") or r.get("room") or "",
            "contact": r.get("contact_name") or "",
            "guest_count": r.get("guest_count") or r.get("guests") or 0,
            "description": r.get("description") or "",
        }
