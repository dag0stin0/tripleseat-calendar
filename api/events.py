"""
Vercel Serverless Function — /api/events
Returns normalized events from CSV data files or Tripleseat API.
Query params: ?start=YYYY-MM-DD&end=YYYY-MM-DD
"""

import os
import re
import csv
import json
import logging
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

EVENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "events")


# ── CSV Loading ────────────────────────────────────────────

def _parse_csv_time(date_str, time_str):
    """Parse date + time from CSV into ISO format string."""
    if not date_str or not time_str:
        return ""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %I:%M %p")
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return ""


def load_csv_events():
    """Load all events from CSV files in the events/ directory."""
    items = []
    if not os.path.isdir(EVENTS_DIR):
        return items

    csv_files = sorted(f for f in os.listdir(EVENTS_DIR) if f.endswith(".csv"))
    event_id = 1

    for filename in csv_files:
        filepath = os.path.join(EVENTS_DIR, filename)
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                start = _parse_csv_time(row.get("Date", ""), row.get("Start Time", ""))
                end = _parse_csv_time(row.get("Date", ""), row.get("End Time", ""))
                guests = row.get("Guests", "").strip()
                items.append({
                    "id": event_id,
                    "type": (row.get("Type", "") or "event").lower() or "event",
                    "name": row.get("Name", "Untitled"),
                    "status": (row.get("Status", "") or "").lower(),
                    "start": start,
                    "end": end,
                    "location": row.get("Location", ""),
                    "room": row.get("Rooms", ""),
                    "contact": row.get("Contact", ""),
                    "guest_count": int(guests) if guests.isdigit() else 0,
                    "event_style": row.get("Event Style", ""),
                })
                event_id += 1

    return items


# ── Handler ─────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    @staticmethod
    def _valid_date(s):
        """Return True if s is a valid YYYY-MM-DD string."""
        return bool(s and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        start_str = qs.get("start", [None])[0]
        end_str = qs.get("end", [None])[0]

        # Validate date format
        if start_str and not self._valid_date(start_str):
            self._send_json(400, {"error": "Invalid start date. Use YYYY-MM-DD format."})
            return
        if end_str and not self._valid_date(end_str):
            self._send_json(400, {"error": "Invalid end date. Use YYYY-MM-DD format."})
            return

        try:
            items = load_csv_events()

            if start_str and end_str:
                items = [i for i in items if start_str <= i["start"][:10] <= end_str]

            items.sort(key=lambda x: x.get("start", ""))
            self._send_json(200, {"items": items, "demo": False})

        except Exception as e:
            logger.exception("Failed to load events")
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
