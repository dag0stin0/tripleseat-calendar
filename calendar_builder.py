"""
Weekly Calendar HTML Builder
Generates a clean, printable HTML calendar from Tripleseat events and bookings.
"""

from datetime import datetime, timedelta
from collections import defaultdict
import html as html_mod


def get_week_range(reference_date=None):
    """Get Monday–Sunday date range for the week containing reference_date."""
    if reference_date is None:
        reference_date = datetime.now()
    monday = reference_date - timedelta(days=reference_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0), \
           sunday.replace(hour=23, minute=59, second=59, microsecond=0)


def parse_datetime(dt_string):
    """Parse a datetime string from Tripleseat (tries common formats)."""
    if not dt_string:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y",
    ]:
        try:
            return datetime.strptime(dt_string, fmt)
        except (ValueError, TypeError):
            continue
    return None


def normalize_event(raw_event):
    """
    Normalize a Tripleseat event into a standard dict.
    Tripleseat nests event data — handle both flat and nested structures.
    """
    e = raw_event.get("event", raw_event)
    return {
        "id": e.get("id"),
        "type": "event",
        "name": e.get("name") or e.get("event_name") or "Untitled Event",
        "status": e.get("status") or e.get("event_status") or "",
        "start": parse_datetime(e.get("event_start") or e.get("start_date") or e.get("event_date")),
        "end": parse_datetime(e.get("event_end") or e.get("end_date")),
        "location": e.get("location_name") or e.get("location") or "",
        "room": e.get("room_name") or e.get("room") or "",
        "contact": e.get("contact_name") or "",
        "guest_count": e.get("guest_count") or e.get("guests") or "",
        "description": e.get("description") or "",
    }


def normalize_booking(raw_booking):
    """Normalize a Tripleseat booking into a standard dict."""
    b = raw_booking.get("booking", raw_booking)
    return {
        "id": b.get("id"),
        "type": "booking",
        "name": b.get("name") or b.get("booking_name") or "Untitled Booking",
        "status": b.get("status") or b.get("booking_status") or "",
        "start": parse_datetime(b.get("start") or b.get("start_date") or b.get("booking_start")),
        "end": parse_datetime(b.get("end") or b.get("end_date") or b.get("booking_end")),
        "location": b.get("location_name") or b.get("location") or "",
        "room": b.get("room_name") or b.get("room") or "",
        "contact": b.get("contact_name") or "",
        "guest_count": b.get("guest_count") or b.get("guests") or "",
        "description": b.get("description") or "",
    }


def group_by_day(items, week_start, week_end):
    """Group normalized items into day buckets (Mon–Sun)."""
    days = defaultdict(list)
    for item in items:
        dt = item.get("start")
        if dt is None:
            continue
        # Strip timezone info for comparison if needed
        dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
        ws_naive = week_start.replace(tzinfo=None) if week_start.tzinfo else week_start
        we_naive = week_end.replace(tzinfo=None) if week_end.tzinfo else week_end
        if ws_naive <= dt_naive <= we_naive:
            day_key = dt_naive.strftime("%Y-%m-%d")
            days[day_key].append(item)

    # Sort each day's items by start time
    for day in days:
        days[day].sort(key=lambda x: x["start"] or datetime.min)

    return days


def _no_pad(dt, fmt):
    """Cross-platform strftime that removes leading zeros (works on Windows too)."""
    return dt.strftime(fmt.replace("-", "#") if __import__("os").name == "nt" else fmt)


def format_time(dt):
    """Format a datetime as a friendly time string."""
    if dt is None:
        return ""
    return _no_pad(dt, "%-I:%M %p").lower()


def build_calendar_html(events, bookings, week_start=None, week_end=None,
                        title="Weekly Event Calendar"):
    """
    Build a complete HTML weekly calendar.

    Args:
        events: List of raw event dicts from Tripleseat API
        bookings: List of raw booking dicts from Tripleseat API
        week_start: Monday datetime (auto-calculated if None)
        week_end: Sunday datetime (auto-calculated if None)
        title: Calendar title

    Returns:
        Complete HTML string
    """
    if week_start is None or week_end is None:
        week_start, week_end = get_week_range()

    # Normalize all items
    all_items = []
    for e in events:
        all_items.append(normalize_event(e))
    for b in bookings:
        all_items.append(normalize_booking(b))

    # Group by day
    grouped = group_by_day(all_items, week_start, week_end)

    # Generate day columns
    days_html = []
    current = week_start
    total_count = 0
    for i in range(7):
        day_key = current.strftime("%Y-%m-%d")
        day_name = current.strftime("%A")
        day_date = _no_pad(current, "%b %-d")
        items = grouped.get(day_key, [])
        total_count += len(items)

        is_today = current.date() == datetime.now().date()
        today_class = " today" if is_today else ""

        items_html = ""
        if not items:
            items_html = '<div class="empty">No events</div>'
        else:
            for item in items:
                esc = html_mod.escape
                type_class = item["type"]
                status_badge = ""
                if item["status"]:
                    status_class = item["status"].lower().replace(" ", "-")
                    status_badge = f'<span class="status {status_class}">{esc(item["status"])}</span>'

                time_str = format_time(item["start"])
                end_str = format_time(item["end"])
                time_display = time_str
                if end_str:
                    time_display = f"{time_str} – {end_str}"

                location_str = ""
                if item["location"] or item["room"]:
                    parts = [p for p in [item["location"], item["room"]] if p]
                    location_str = f'<div class="location">📍 {esc(" · ".join(parts))}</div>'

                contact_str = ""
                if item["contact"]:
                    contact_str = f'<div class="contact">👤 {esc(item["contact"])}</div>'

                guest_str = ""
                if item["guest_count"]:
                    guest_str = f'<div class="guests">👥 {esc(str(item["guest_count"]))} guests</div>'

                items_html += f"""
                <div class="item {type_class}">
                    <div class="item-header">
                        <span class="type-badge {type_class}">{item["type"].title()}</span>
                        {status_badge}
                    </div>
                    <div class="item-name">{esc(item["name"])}</div>
                    <div class="time">{time_display}</div>
                    {location_str}
                    {contact_str}
                    {guest_str}
                </div>"""

        days_html.append(f"""
        <div class="day-column{today_class}">
            <div class="day-header">
                <div class="day-name">{day_name}</div>
                <div class="day-date">{day_date}</div>
                <div class="day-count">{len(items)} event{"s" if len(items) != 1 else ""}</div>
            </div>
            <div class="day-body">
                {items_html}
            </div>
        </div>""")

        current += timedelta(days=1)

    week_label = f"{_no_pad(week_start, '%B %-d')} – {_no_pad(week_end, '%B %-d, %Y')}"
    generated = _no_pad(datetime.now(), "%B %-d, %Y at %-I:%M %p")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(title)} — {week_label}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #f0f2f5;
        color: #1a1a2e;
        padding: 24px;
        min-height: 100vh;
    }}

    .header {{
        text-align: center;
        margin-bottom: 28px;
    }}

    .header h1 {{
        font-size: 26px;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 6px;
    }}

    .header .week-range {{
        font-size: 16px;
        color: #555;
        font-weight: 500;
    }}

    .header .summary {{
        font-size: 13px;
        color: #888;
        margin-top: 4px;
    }}

    .calendar {{
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 10px;
        max-width: 1400px;
        margin: 0 auto;
    }}

    .day-column {{
        background: #fff;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        min-height: 300px;
        display: flex;
        flex-direction: column;
    }}

    .day-column.today {{
        box-shadow: 0 0 0 2px #4361ee, 0 2px 8px rgba(67,97,238,0.15);
    }}

    .day-header {{
        padding: 14px 14px 10px;
        border-bottom: 1px solid #eee;
        background: #fafbfc;
    }}

    .today .day-header {{
        background: #4361ee;
        border-bottom-color: #4361ee;
    }}

    .today .day-header .day-name,
    .today .day-header .day-date,
    .today .day-header .day-count {{
        color: #fff !important;
    }}

    .day-name {{
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #888;
    }}

    .day-date {{
        font-size: 20px;
        font-weight: 700;
        color: #1a1a2e;
        margin-top: 2px;
    }}

    .day-count {{
        font-size: 11px;
        color: #aaa;
        margin-top: 2px;
    }}

    .day-body {{
        padding: 10px;
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }}

    .empty {{
        color: #ccc;
        font-size: 13px;
        text-align: center;
        padding: 20px 0;
        font-style: italic;
    }}

    .item {{
        padding: 10px 12px;
        border-radius: 8px;
        border-left: 3px solid #4361ee;
        background: #f8f9ff;
        font-size: 13px;
    }}

    .item.booking {{
        border-left-color: #2ec4b6;
        background: #f0faf9;
    }}

    .item-header {{
        display: flex;
        gap: 6px;
        align-items: center;
        margin-bottom: 4px;
    }}

    .type-badge {{
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 2px 6px;
        border-radius: 4px;
        background: #e8edff;
        color: #4361ee;
    }}

    .type-badge.booking {{
        background: #d4f5f0;
        color: #1a9988;
    }}

    .status {{
        font-size: 10px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 4px;
        background: #f0f0f0;
        color: #666;
    }}

    .status.confirmed, .status.definite {{
        background: #d4edda;
        color: #155724;
    }}

    .status.tentative, .status.prospect {{
        background: #fff3cd;
        color: #856404;
    }}

    .status.cancelled, .status.closed-lost {{
        background: #f8d7da;
        color: #721c24;
        text-decoration: line-through;
    }}

    .item-name {{
        font-weight: 600;
        font-size: 14px;
        color: #1a1a2e;
        margin-bottom: 4px;
    }}

    .time {{
        color: #555;
        font-size: 12px;
        margin-bottom: 3px;
    }}

    .location, .contact, .guests {{
        font-size: 12px;
        color: #777;
        margin-top: 2px;
    }}

    .footer {{
        text-align: center;
        margin-top: 24px;
        font-size: 11px;
        color: #bbb;
    }}

    /* Print styles */
    @media print {{
        body {{
            background: #fff;
            padding: 12px;
        }}
        .calendar {{
            gap: 4px;
        }}
        .day-column {{
            box-shadow: none;
            border: 1px solid #ddd;
            min-height: auto;
        }}
        .day-column.today {{
            box-shadow: none;
            border: 2px solid #4361ee;
        }}
        .item {{
            page-break-inside: avoid;
        }}
    }}

    /* Responsive — stack on small screens */
    @media (max-width: 900px) {{
        .calendar {{
            grid-template-columns: 1fr;
            max-width: 500px;
        }}
        .day-column {{
            min-height: auto;
        }}
    }}
</style>
</head>
<body>
    <div class="header">
        <h1>{html_mod.escape(title)}</h1>
        <div class="week-range">{week_label}</div>
        <div class="summary">{total_count} total events &amp; bookings this week</div>
    </div>
    <div class="calendar">
        {"".join(days_html)}
    </div>
    <div class="footer">
        Generated {generated} · Powered by Tripleseat API
    </div>
</body>
</html>"""
