"""
Vercel Serverless Function — /api/events
Returns normalized events + bookings from Tripleseat API.
Query params: ?start=YYYY-MM-DD&end=YYYY-MM-DD
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# ── Tripleseat Client (inline for serverless) ──────────────

API_BASE = "https://api.tripleseat.com/v1"
RATE_LIMIT_INTERVAL = 0.1

_last_request_time = 0


def ts_request(session, endpoint, params=None):
    """Make a rate-limited GET request to Tripleseat."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < RATE_LIMIT_INTERVAL:
        time.sleep(RATE_LIMIT_INTERVAL - elapsed)
    _last_request_time = time.time()

    url = f"{API_BASE}{endpoint}.json"
    params = params or {}
    api_key = os.environ.get("TRIPLESEAT_API_KEY", "")
    if api_key:
        params["api_key"] = api_key

    resp = session.get(url, params=params, timeout=30)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        time.sleep(retry_after)
        return ts_request(session, endpoint, params)

    resp.raise_for_status()
    return resp.json()


def ts_fetch_all(session, endpoint, params=None, max_pages=50):
    """Paginate through a Tripleseat endpoint."""
    params = params or {}
    all_results = []
    page = 1

    while page <= max_pages:
        params["page"] = page
        data = ts_request(session, endpoint, params)

        results = []
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    results = value
                    break
            if not results and "results" in data:
                results = data["results"]
        elif isinstance(data, list):
            results = data

        if not results:
            break

        all_results.extend(results)
        if len(results) < 25:
            break
        page += 1

    return all_results


def get_session():
    """Create an OAuth1 session for Tripleseat."""
    from requests_oauthlib import OAuth1Session
    return OAuth1Session(
        client_key=os.environ.get("TRIPLESEAT_CONSUMER_KEY", ""),
        client_secret=os.environ.get("TRIPLESEAT_CONSUMER_SECRET", ""),
    )


# ── Normalization ───────────────────────────────────────────

def normalize(raw, kind="event"):
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
        }


# ── Demo Data ───────────────────────────────────────────────

def generate_demo_data():
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    names = [
        ("Johnson Wedding Reception", "confirmed", "Grand Ballroom", "Sarah Johnson", 150),
        ("Tech Corp Annual Dinner", "confirmed", "Rooftop Terrace", "Mike Chen", 80),
        ("Birthday — Martinez Family", "tentative", "Private Dining Room", "Ana Martinez", 35),
        ("Charity Gala 2026", "confirmed", "Grand Ballroom", "David Park", 200),
        ("Corporate Lunch — Acme Inc", "prospect", "Garden Room", "Lisa Wong", 25),
        ("Rehearsal Dinner — Kim/Patel", "confirmed", "Wine Cellar", "Priya Patel", 40),
        ("Sunday Brunch — Book Club", "tentative", "Patio", "Rachel Green", 15),
        ("Product Launch Happy Hour", "confirmed", "Lounge Bar", "Tom Baker", 60),
        ("Staff Training Lunch", "confirmed", "Conference Room A", "HR Team", 30),
        ("Wine Tasting Evening", "tentative", "Wine Cellar", "James Noir", 20),
        ("Board Meeting Luncheon", "confirmed", "Executive Suite", "CFO Office", 12),
        ("Anniversary Party — Lee", "confirmed", "Garden Room", "Jenny Lee", 75),
        ("Networking Mixer", "prospect", "Lounge Bar", "BizDev Team", 50),
        ("Holiday Planning Committee", "tentative", "Conference Room A", "Events Team", 8),
        ("VIP Tasting Menu Preview", "confirmed", "Private Dining Room", "Chef Marco", 18),
    ]
    times = [
        (10,0,14,0),(18,0,22,0),(12,0,15,0),(17,0,23,0),(11,30,13,30),
        (18,30,21,0),(10,0,12,0),(17,0,20,0),(12,0,13,30),(19,0,21,30),
        (12,0,14,0),(16,0,22,0),(17,30,20,0),(10,0,11,0),(19,0,22,0),
    ]
    days = [0,1,2,2,3,4,6,3,8,5,7,9,10,8,11]

    items = []
    for i, (name, status, room, contact, guests) in enumerate(names):
        sh, sm, eh, em = times[i]
        start = (monday + timedelta(days=days[i])).replace(hour=sh, minute=sm)
        end = (monday + timedelta(days=days[i])).replace(hour=eh, minute=em)
        items.append({
            "id": 1000 + i,
            "type": "booking" if i % 4 == 0 else "event",
            "name": name, "status": status,
            "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "location": "The Grand Venue", "room": room,
            "contact": contact, "guest_count": guests,
        })
    return items


# ── Handler ─────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        start_str = qs.get("start", [None])[0]
        end_str = qs.get("end", [None])[0]

        consumer_key = os.environ.get("TRIPLESEAT_CONSUMER_KEY", "")
        consumer_secret = os.environ.get("TRIPLESEAT_CONSUMER_SECRET", "")
        use_demo = not consumer_key or not consumer_secret

        if use_demo:
            items = generate_demo_data()
            if start_str and end_str:
                items = [i for i in items if start_str <= i["start"][:10] <= end_str]
            body = json.dumps({"items": items, "demo": True})
        else:
            try:
                session = get_session()
                params = {}
                if start_str:
                    params["start_date"] = start_str
                if end_str:
                    params["end_date"] = end_str

                raw_events = ts_fetch_all(session, "/events/search", dict(params)) if params else ts_fetch_all(session, "/events")
                raw_bookings = ts_fetch_all(session, "/bookings/search", dict(params)) if params else ts_fetch_all(session, "/bookings")

                items = [normalize(e, "event") for e in raw_events]
                items += [normalize(b, "booking") for b in raw_bookings]
                items.sort(key=lambda x: x.get("start", ""))

                body = json.dumps({"items": items, "demo": False})
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())
