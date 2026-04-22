"""
Vercel Serverless Function — /api/events
Returns normalized events, preferring Tripleseat live API and falling back to CSV.

Query params:
    start   YYYY-MM-DD (inclusive)
    end     YYYY-MM-DD (inclusive)
    source  csv | tripleseat  (optional override for debugging)
"""

import os
import re
import csv
import json
import logging
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Ensure parent dir is importable for tripleseat_client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

EVENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "events")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ── Currency parsing ──────────────────────────────────────

def _parse_money(v):
    """Parse '$1,500.00' / '1500' / '' → float or None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", s)
    if not cleaned or cleaned in (".", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ── CSV Loading ────────────────────────────────────────────

def _parse_csv_time(date_str, time_str):
    if not date_str or not time_str:
        return ""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %I:%M %p")
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return ""


def _loc_key(location: str) -> str:
    loc = (location or "").lower()
    return "dc" if "dc" in loc else "nyc"


def load_csv_events():
    """Load all events from CSV files in events/."""
    items = []
    if not os.path.isdir(EVENTS_DIR):
        return items

    event_id = 1
    for filename in sorted(f for f in os.listdir(EVENTS_DIR) if f.endswith(".csv")):
        filepath = os.path.join(EVENTS_DIR, filename)
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    start = _parse_csv_time(row.get("Date", ""), row.get("Start Time", ""))
                    end = _parse_csv_time(row.get("Date", ""), row.get("End Time", ""))
                    guests = (row.get("Guests", "") or "").strip()
                    items.append({
                        "id": event_id,
                        "source": "csv",
                        "type": ((row.get("Type", "") or "event").lower()) or "event",
                        "name": row.get("Name", "Untitled"),
                        "status": (row.get("Status", "") or "").lower(),
                        "start": start,
                        "end": end,
                        "location": row.get("Location", ""),
                        "locKey": _loc_key(row.get("Location", "")),
                        "room": row.get("Rooms", ""),
                        "contact": row.get("Contact", ""),
                        "guest_count": int(guests) if guests.isdigit() else 0,
                        "event_style": row.get("Event Style", ""),
                        "fb_min": _parse_money(row.get("Event F&B Min")),
                        "grand_total": _parse_money(row.get("Event Grand Total")),
                        "deposit": _parse_money(row.get("Deposit")),
                        "amount_due": _parse_money(row.get("Amount Due")),
                        "actual": _parse_money(row.get("Event Actual")),
                    })
                    event_id += 1
        except Exception as e:
            logger.warning("Failed to read %s: %s", filename, e)

    return items


# ── Tripleseat live ────────────────────────────────────────

def _as_str(v):
    """Coerce Tripleseat values to a plain string. Unwraps {name|title|value} dicts."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in ("name", "title", "label", "value"):
            inner = v.get(k)
            if isinstance(inner, str) and inner:
                return inner
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(_as_str(x) for x in v if x)
    return str(v)


_TS_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %I:%M %p",
    "%Y-%m-%d %I:%M%p",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    # Tripleseat commonly returns US-style dates
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %I:%M%p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y %I:%M %p",
    "%m-%d-%Y",
)


def _ts_iso(v, time_hint=None):
    """Normalize Tripleseat date/time payloads to 'YYYY-MM-DDTHH:MM:SS'.

    time_hint may be a separate time string (Tripleseat sometimes splits
    date and time across two fields, e.g. 'event_date' + 'start_time_only')."""
    if not v:
        return ""
    s = str(v).strip()
    if not s:
        return ""

    # If we have a date and a separate time component, try them together first
    if time_hint:
        combo = f"{s} {str(time_hint).strip()}"
        for fmt in _TS_DATE_FORMATS:
            try:
                return datetime.strptime(combo, fmt).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue

    for fmt in _TS_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return ""  # unparseable — drop rather than ship a bad string


def _ts_contact(raw):
    """Extract a contact display name from Tripleseat-shaped contact blobs."""
    c = raw.get("contact") or raw.get("booking_contact") or raw.get("lead_contact") or {}
    if isinstance(c, dict):
        first = _as_str(c.get("first_name"))
        last  = _as_str(c.get("last_name"))
        joined = (first + " " + last).strip()
        return joined or _as_str(c.get("name")) or _as_str(c.get("full_name")) or ""
    return _as_str(c)


def _ts_map_event(raw, eid):
    """Map a Tripleseat event dict to our normalized shape.
    Defensive — Tripleseat returns many fields as nested dicts or lists."""
    location = _as_str(raw.get("site_name")) \
        or _as_str(raw.get("location_name")) \
        or _as_str(raw.get("site")) \
        or _as_str(raw.get("location"))

    rooms = _as_str(raw.get("rooms")) or _as_str(raw.get("room"))
    contact = _ts_contact(raw)
    status = _as_str(raw.get("status") or raw.get("event_status")).lower()
    event_type = _as_str(raw.get("event_type") or raw.get("type") or "event").lower() or "event"
    event_style = _as_str(raw.get("event_style") or raw.get("style"))
    name = _as_str(raw.get("name") or raw.get("title")) or "Untitled"

    guest_count = raw.get("guest_count") or raw.get("guests") or 0
    if isinstance(guest_count, dict):
        guest_count = guest_count.get("count") or guest_count.get("value") or 0
    try:
        guest_count = int(guest_count)
    except (TypeError, ValueError):
        guest_count = 0

    return {
        "id": raw.get("id", eid),
        "source": "tripleseat",
        "type": event_type,
        "name": name,
        "status": status,
        "start": _ts_iso(
            raw.get("event_start") or raw.get("start_time") or
            raw.get("start_date") or raw.get("event_date") or raw.get("date"),
            time_hint=raw.get("start_time_only") or raw.get("event_start_time")
        ),
        "end": _ts_iso(
            raw.get("event_end") or raw.get("end_time") or
            raw.get("end_date") or raw.get("event_date") or raw.get("date"),
            time_hint=raw.get("end_time_only") or raw.get("event_end_time")
        ),
        "location": location,
        "locKey": _loc_key(location),
        "room": rooms,
        "contact": contact,
        "guest_count": guest_count,
        "event_style": event_style,
        "fb_min":      _parse_money(raw.get("food_beverage_minimum") or raw.get("fb_min")),
        "grand_total": _parse_money(raw.get("grand_total") or raw.get("total")),
        "deposit":     _parse_money(raw.get("deposit")),
        "amount_due":  _parse_money(raw.get("amount_due") or raw.get("balance_due")),
        "actual":      _parse_money(raw.get("actual_revenue") or raw.get("actual")),
    }


def load_tripleseat_events(start: str, end: str):
    """Fetch + normalize Tripleseat events. Returns (items, None) on success, ([], error_str)."""
    ck = os.environ.get("TRIPLESEAT_CONSUMER_KEY")
    cs = os.environ.get("TRIPLESEAT_CONSUMER_SECRET")
    api = os.environ.get("TRIPLESEAT_API_KEY")

    if not (ck and cs):
        return [], "missing_credentials"

    try:
        from tripleseat_client import TripleseatClient
    except ImportError as e:
        return [], f"client_import_failed: {e}"

    try:
        client = TripleseatClient(consumer_key=ck, consumer_secret=cs, api_key=api)
        params = {"max_pages": 20}  # ~500 events max — comfortable under 30s lambda budget
        if start:
            params["start_date"] = start
        if end:
            params["end_date"] = end
        params["order"] = "event_start"
        params["sort_direction"] = "asc"
        raw_events = client.search_events(**params)

        items = []
        skipped = 0
        for idx, r in enumerate(raw_events or []):
            try:
                mapped = _ts_map_event(r, idx + 1)
                if mapped["start"]:
                    items.append(mapped)
                else:
                    skipped += 1
            except Exception as e:
                logger.warning("Skipping Tripleseat record %s: %s", idx, e)
                skipped += 1
        if skipped:
            logger.info("Mapped %d events, skipped %d malformed", len(items), skipped)
        return items, None
    except Exception as e:
        logger.exception("Tripleseat fetch failed")
        return [], f"request_failed: {e}"


# ── Handler ─────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    @staticmethod
    def _valid_date(s):
        return bool(s and DATE_RE.fullmatch(s))

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        start_str = qs.get("start", [None])[0]
        end_str = qs.get("end", [None])[0]
        source_override = (qs.get("source", [None])[0] or "").lower()

        for label, val in (("start", start_str), ("end", end_str)):
            if val and not self._valid_date(val):
                return self._send_json(400, {"error": f"Invalid {label} date. Use YYYY-MM-DD."})

        # Default window if caller omits: past 60 days → next 365 days.
        # Without this the Tripleseat path would fetch every event ever,
        # which blows past the lambda's execution budget.
        if not start_str:
            start_str = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")
        if not end_str:
            end_str = (datetime.utcnow() + timedelta(days=365)).strftime("%Y-%m-%d")

        items = []
        source = "csv"
        notes = []

        # 1. Try Tripleseat unless explicitly asking for csv
        if source_override != "csv":
            ts_items, ts_err = load_tripleseat_events(start_str, end_str)
            if ts_items:
                items = ts_items
                source = "tripleseat"
            elif source_override == "tripleseat":
                # User explicitly asked for Tripleseat only
                return self._send_json(502, {"error": f"Tripleseat unavailable: {ts_err}"})
            else:
                if ts_err and ts_err != "missing_credentials":
                    notes.append(f"tripleseat_fallback: {ts_err}")

        # 2. CSV fallback
        if not items:
            try:
                items = load_csv_events()
            except Exception as e:
                logger.exception("CSV load failed")
                return self._send_json(500, {"error": str(e)})

        # 3. Date filter (applies to both Tripleseat and CSV; Tripleseat's
        #    search_events params are unreliable, so filter here too)
        if start_str and end_str:
            items = [i for i in items
                     if i.get("start") and start_str <= i["start"][:10] <= end_str]

        items.sort(key=lambda x: x.get("start", ""))

        payload = {
            "items": items,
            "count": len(items),
            "source": source,
            "fetched_at": datetime.utcnow().isoformat() + "Z",
        }
        if notes:
            payload["notes"] = notes
        self._send_json(200, payload)

    def _send_json(self, status, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=60, stale-while-revalidate=300")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
