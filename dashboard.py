#!/usr/bin/env python3
"""
Tripleseat Team Dashboard
=========================
A live web dashboard that pulls events and bookings from your Tripleseat
account and presents them in a team-friendly view.

Usage:
  pip install flask requests requests-oauthlib
  python dashboard.py              # Starts on http://localhost:5050
  python dashboard.py --demo       # Uses sample data (no API needed)
  python dashboard.py --port 8080  # Custom port

Environment variables (or .env file):
  TRIPLESEAT_CONSUMER_KEY    OAuth 1.0 consumer key
  TRIPLESEAT_CONSUMER_SECRET OAuth 1.0 consumer secret
  TRIPLESEAT_API_KEY         Optional API key
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from flask import Flask, jsonify, request, Response

# ── Load .env ───────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

from tripleseat_client import TripleseatClient
from calendar_builder import parse_datetime

# ── App Setup ───────────────────────────────────────────────
app = Flask(__name__)
logger = logging.getLogger(__name__)

# Global state
_client = None
_demo_mode = False


def get_client():
    global _client
    if _client is None and not _demo_mode:
        consumer_key = os.environ.get("TRIPLESEAT_CONSUMER_KEY", "")
        consumer_secret = os.environ.get("TRIPLESEAT_CONSUMER_SECRET", "")
        api_key = os.environ.get("TRIPLESEAT_API_KEY", "")
        if not consumer_key or not consumer_secret:
            logger.error("Missing TRIPLESEAT_CONSUMER_KEY / TRIPLESEAT_CONSUMER_SECRET")
            return None
        _client = TripleseatClient(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            api_key=api_key or None,
        )
    return _client


# ── Data Normalization ──────────────────────────────────────

def normalize(raw, kind="event"):
    """Normalize a raw Tripleseat record into a flat dict."""
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


# ── Demo Data ───────────────────────────────────────────────

def generate_demo_data():
    """Generate realistic demo data for the current and next week."""
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    events = []
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
        (10, 0, 14, 0), (18, 0, 22, 0), (12, 0, 15, 0),
        (17, 0, 23, 0), (11, 30, 13, 30), (18, 30, 21, 0),
        (10, 0, 12, 0), (17, 0, 20, 0), (12, 0, 13, 30),
        (19, 0, 21, 30), (12, 0, 14, 0), (16, 0, 22, 0),
        (17, 30, 20, 0), (10, 0, 11, 0), (19, 0, 22, 0),
    ]

    days = [0, 1, 2, 2, 3, 4, 6, 3, 8, 5, 7, 9, 10, 8, 11]

    for i, (name, status, room, contact, guests) in enumerate(names):
        day_offset = days[i]
        sh, sm, eh, em = times[i]
        start = (monday + timedelta(days=day_offset)).replace(hour=sh, minute=sm)
        end = (monday + timedelta(days=day_offset)).replace(hour=eh, minute=em)

        entry = {
            "id": 1000 + i,
            "type": "booking" if i % 4 == 0 else "event",
            "name": name,
            "status": status,
            "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "location": "The Grand Venue",
            "room": room,
            "contact": contact,
            "guest_count": guests,
            "description": "",
        }
        events.append(entry)

    return events


# ── API Endpoints ───────────────────────────────────────────

@app.route("/api/events")
def api_events():
    """
    GET /api/events?start=YYYY-MM-DD&end=YYYY-MM-DD
    Returns normalized events + bookings for the date range.
    """
    start_str = request.args.get("start")
    end_str = request.args.get("end")

    if _demo_mode:
        items = generate_demo_data()
        # Filter by date range if provided
        if start_str and end_str:
            items = [
                i for i in items
                if start_str <= i["start"][:10] <= end_str
            ]
        return jsonify({"items": items, "demo": True})

    client = get_client()
    if client is None:
        return jsonify({"error": "API credentials not configured"}), 500

    try:
        params = {}
        if start_str:
            params["start_date"] = start_str
        if end_str:
            params["end_date"] = end_str

        raw_events = client.search_events(**params) if params else client.get_events()
        raw_bookings = client.search_bookings(**params) if params else client.get_bookings()

        items = []
        for e in raw_events:
            items.append(normalize(e, "event"))
        for b in raw_bookings:
            items.append(normalize(b, "booking"))

        items.sort(key=lambda x: x.get("start", ""))
        return jsonify({"items": items, "demo": False})

    except Exception as e:
        logger.exception("Failed to fetch from Tripleseat")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    """Quick stats endpoint — delegates to /api/events internally."""
    with app.test_request_context(f"/api/events?{request.query_string.decode()}"):
        resp = api_events()
        if isinstance(resp, tuple):
            return resp
        data = resp.get_json()

    items = data.get("items", [])
    statuses = defaultdict(int)
    rooms = defaultdict(int)
    total_guests = 0

    for item in items:
        statuses[item.get("status", "unknown")] += 1
        if item.get("room"):
            rooms[item["room"]] += 1
        total_guests += int(item.get("guest_count", 0) or 0)

    return jsonify({
        "total": len(items),
        "total_guests": total_guests,
        "by_status": dict(statuses),
        "by_room": dict(rooms),
    })


# ── Dashboard HTML ──────────────────────────────────────────

@app.route("/")
def dashboard():
    return Response(DASHBOARD_HTML, mimetype="text/html")


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tripleseat — Team Dashboard</title>
<style>
:root {
    --bg: #f0f2f5;
    --surface: #ffffff;
    --text: #1a1a2e;
    --text-secondary: #64748b;
    --border: #e2e8f0;
    --accent: #4361ee;
    --accent-light: #e8edff;
    --green: #22c55e;
    --green-light: #dcfce7;
    --yellow: #eab308;
    --yellow-light: #fef9c3;
    --red: #ef4444;
    --red-light: #fee2e2;
    --teal: #14b8a6;
    --teal-light: #ccfbf1;
    --purple: #8b5cf6;
    --purple-light: #ede9fe;
    --radius: 12px;
    --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 6px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
}

/* ── Top Bar ────────────────────────────── */
.topbar {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: var(--shadow);
}

.topbar-left {
    display: flex;
    align-items: center;
    gap: 16px;
}

.topbar h1 {
    font-size: 20px;
    font-weight: 700;
    color: var(--text);
}

.topbar .badge {
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    background: var(--accent-light);
    color: var(--accent);
}

.topbar-right {
    display: flex;
    align-items: center;
    gap: 12px;
}

.topbar-right select, .topbar-right button {
    font-size: 13px;
    padding: 8px 14px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
    font-family: inherit;
}

.topbar-right button {
    background: var(--accent);
    color: #fff;
    border: none;
    font-weight: 600;
}

.topbar-right button:hover { opacity: 0.9; }

.refresh-indicator {
    font-size: 11px;
    color: var(--text-secondary);
}

/* ── Main Layout ────────────────────────── */
.main {
    max-width: 1440px;
    margin: 0 auto;
    padding: 24px 32px;
}

/* ── Stat Cards ─────────────────────────── */
.stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.stat-card {
    background: var(--surface);
    border-radius: var(--radius);
    padding: 20px 24px;
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.stat-card .label {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
}

.stat-card .value {
    font-size: 32px;
    font-weight: 700;
    line-height: 1.1;
}

.stat-card .sub {
    font-size: 12px;
    color: var(--text-secondary);
}

.stat-card.accent .value { color: var(--accent); }
.stat-card.green .value { color: var(--green); }
.stat-card.yellow .value { color: var(--yellow); }
.stat-card.teal .value { color: var(--teal); }
.stat-card.purple .value { color: var(--purple); }

/* ── Filters ────────────────────────────── */
.filters {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
}

.filter-chip {
    font-size: 12px;
    font-weight: 600;
    padding: 6px 14px;
    border-radius: 20px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.15s;
}

.filter-chip:hover { border-color: var(--accent); color: var(--accent); }
.filter-chip.active { background: var(--accent); color: #fff; border-color: var(--accent); }

/* ── Week Navigation ────────────────────── */
.week-nav {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 20px;
}

.week-nav button {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    color: var(--text);
    font-family: inherit;
}

.week-nav button:hover { border-color: var(--accent); color: var(--accent); }

.week-nav .week-label {
    font-size: 16px;
    font-weight: 600;
}

.week-nav .today-btn {
    font-size: 12px;
    color: var(--accent);
    cursor: pointer;
    font-weight: 600;
    background: none;
    border: none;
    padding: 0;
}

.week-nav .today-btn:hover { text-decoration: underline; }

/* ── Calendar Grid ──────────────────────── */
.calendar {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 12px;
    margin-bottom: 32px;
}

.day-col {
    background: var(--surface);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    min-height: 280px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.day-col.today { box-shadow: 0 0 0 2px var(--accent), var(--shadow-md); }

.day-head {
    padding: 14px 14px 10px;
    border-bottom: 1px solid var(--border);
    background: #fafbfc;
}

.day-col.today .day-head {
    background: var(--accent);
    border-bottom-color: var(--accent);
}
.day-col.today .day-head * { color: #fff !important; }

.day-head .dname {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-secondary);
}

.day-head .ddate {
    font-size: 20px;
    font-weight: 700;
    color: var(--text);
    margin-top: 2px;
}

.day-head .dcount {
    font-size: 11px;
    color: #aaa;
    margin-top: 2px;
}

.day-body {
    padding: 10px;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow-y: auto;
}

.day-body .empty {
    color: #ccc;
    font-size: 13px;
    text-align: center;
    padding: 20px 0;
    font-style: italic;
}

/* ── Event Cards ────────────────────────── */
.ev-card {
    padding: 10px 12px;
    border-radius: 8px;
    border-left: 3px solid var(--accent);
    background: var(--accent-light);
    font-size: 13px;
    cursor: default;
    transition: transform 0.1s;
}

.ev-card:hover { transform: translateY(-1px); }

.ev-card.booking { border-left-color: var(--teal); background: var(--teal-light); }

.ev-card .ev-badges {
    display: flex;
    gap: 5px;
    align-items: center;
    margin-bottom: 4px;
}

.ev-card .type-tag {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 2px 6px;
    border-radius: 4px;
}

.ev-card .type-tag.event { background: var(--accent-light); color: var(--accent); }
.ev-card .type-tag.booking { background: var(--teal-light); color: #0d9488; }

.ev-card .status-tag {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 4px;
    background: #f0f0f0;
    color: #666;
}

.status-tag.confirmed, .status-tag.definite { background: var(--green-light); color: #166534; }
.status-tag.tentative, .status-tag.prospect { background: var(--yellow-light); color: #854d0e; }
.status-tag.cancelled, .status-tag.closed-lost { background: var(--red-light); color: #991b1b; text-decoration: line-through; }

.ev-card .ev-name { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.ev-card .ev-time { color: var(--text-secondary); font-size: 12px; margin-bottom: 3px; }
.ev-card .ev-meta { font-size: 12px; color: #777; margin-top: 2px; }

/* ── Upcoming Table ─────────────────────── */
.section-title {
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 16px;
}

.table-wrap {
    background: var(--surface);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
    margin-bottom: 32px;
}

.table-wrap table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}

.table-wrap th {
    text-align: left;
    padding: 12px 16px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    background: #fafbfc;
    border-bottom: 1px solid var(--border);
}

.table-wrap td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
}

.table-wrap tr:last-child td { border-bottom: none; }
.table-wrap tr:hover td { background: #f8fafc; }

.table-wrap .name-cell { font-weight: 600; }

/* ── Room Breakdown ─────────────────────── */
.rooms-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
}

.room-card {
    background: var(--surface);
    border-radius: var(--radius);
    padding: 16px 20px;
    box-shadow: var(--shadow);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.room-card .room-name { font-weight: 600; font-size: 14px; }
.room-card .room-count {
    font-size: 22px;
    font-weight: 700;
    color: var(--accent);
}

/* ── Loading / Error ────────────────────── */
.loading {
    text-align: center;
    padding: 60px;
    color: var(--text-secondary);
    font-size: 15px;
}

.loading .spinner {
    display: inline-block;
    width: 28px;
    height: 28px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-bottom: 12px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.error-banner {
    background: var(--red-light);
    color: #991b1b;
    padding: 12px 20px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 14px;
    display: none;
}

.demo-banner {
    background: var(--yellow-light);
    color: #854d0e;
    padding: 10px 20px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 13px;
    font-weight: 500;
    text-align: center;
    display: none;
}

/* ── Responsive ─────────────────────────── */
@media (max-width: 1024px) {
    .calendar { grid-template-columns: repeat(4, 1fr); }
}

@media (max-width: 768px) {
    .topbar { padding: 12px 16px; flex-direction: column; gap: 12px; }
    .main { padding: 16px; }
    .calendar { grid-template-columns: 1fr 1fr; }
    .stats-row { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 480px) {
    .calendar { grid-template-columns: 1fr; }
}

@media print {
    .topbar { position: relative; box-shadow: none; }
    .day-col { box-shadow: none; border: 1px solid var(--border); min-height: auto; }
    .day-col.today { box-shadow: none; border: 2px solid var(--accent); }
    .ev-card { break-inside: avoid; }
}
</style>
</head>
<body>

<!-- Top Bar -->
<div class="topbar">
    <div class="topbar-left">
        <h1>Tripleseat Dashboard</h1>
        <span class="badge" id="badge">Loading...</span>
    </div>
    <div class="topbar-right">
        <select id="statusFilter">
            <option value="all">All Statuses</option>
            <option value="confirmed">Confirmed</option>
            <option value="tentative">Tentative</option>
            <option value="prospect">Prospect</option>
        </select>
        <select id="roomFilter">
            <option value="all">All Rooms</option>
        </select>
        <button onclick="refreshData()">Refresh</button>
        <span class="refresh-indicator" id="lastRefresh"></span>
    </div>
</div>

<div class="main">
    <div class="demo-banner" id="demoBanner">
        Demo Mode — showing sample data. Connect your Tripleseat API credentials in <code>.env</code> to see real events.
    </div>
    <div class="error-banner" id="errorBanner"></div>

    <!-- Stats -->
    <div class="stats-row" id="statsRow">
        <div class="stat-card accent">
            <span class="label">Total Events</span>
            <span class="value" id="statTotal">—</span>
            <span class="sub">this week</span>
        </div>
        <div class="stat-card green">
            <span class="label">Confirmed</span>
            <span class="value" id="statConfirmed">—</span>
            <span class="sub">ready to go</span>
        </div>
        <div class="stat-card yellow">
            <span class="label">Tentative</span>
            <span class="value" id="statTentative">—</span>
            <span class="sub">pending confirmation</span>
        </div>
        <div class="stat-card teal">
            <span class="label">Expected Guests</span>
            <span class="value" id="statGuests">—</span>
            <span class="sub">total headcount</span>
        </div>
        <div class="stat-card purple">
            <span class="label">Rooms Booked</span>
            <span class="value" id="statRooms">—</span>
            <span class="sub">unique spaces</span>
        </div>
    </div>

    <!-- Week Nav -->
    <div class="week-nav">
        <button onclick="changeWeek(-1)">&larr; Previous</button>
        <span class="week-label" id="weekLabel"></span>
        <button onclick="changeWeek(1)">Next &rarr;</button>
        <button class="today-btn" onclick="changeWeek(0)">Today</button>
    </div>

    <!-- Filters -->
    <div class="filters" id="filterChips"></div>

    <!-- Calendar Grid -->
    <div id="calendarContainer">
        <div class="loading"><div class="spinner"></div><br>Loading events...</div>
    </div>

    <!-- Upcoming Events Table -->
    <h2 class="section-title">Upcoming Events</h2>
    <div class="table-wrap" id="upcomingTable">
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Event</th>
                    <th>Status</th>
                    <th>Room</th>
                    <th>Contact</th>
                    <th>Guests</th>
                </tr>
            </thead>
            <tbody id="upcomingBody"></tbody>
        </table>
    </div>

    <!-- Rooms Breakdown -->
    <h2 class="section-title">By Room</h2>
    <div class="rooms-grid" id="roomsGrid"></div>
</div>

<script>
// ── State ──────────────────────────────────
let allItems = [];
let weekOffset = 0;
let activeStatusFilter = "all";
let activeRoomFilter = "all";
let refreshTimer = null;

// ── Helpers ────────────────────────────────
function getWeekRange(offset) {
    const now = new Date();
    const day = now.getDay();
    const monday = new Date(now);
    monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1) + (offset * 7));
    monday.setHours(0, 0, 0, 0);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    sunday.setHours(23, 59, 59, 999);
    return { start: monday, end: sunday };
}

function fmt(d) { return d.toISOString().slice(0, 10); }

function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true }).toLowerCase();
}

function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

// ── Data Fetching ──────────────────────────
async function fetchEvents(start, end) {
    const resp = await fetch(`/api/events?start=${fmt(start)}&end=${fmt(end)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

async function refreshData() {
    const { start, end } = getWeekRange(weekOffset);

    // Update week label
    const opts = { month: "long", day: "numeric" };
    const endOpts = { month: "long", day: "numeric", year: "numeric" };
    document.getElementById("weekLabel").textContent =
        `${start.toLocaleDateString("en-US", opts)} – ${end.toLocaleDateString("en-US", endOpts)}`;

    try {
        const data = await fetchEvents(start, end);
        allItems = data.items || [];

        if (data.demo) {
            document.getElementById("demoBanner").style.display = "block";
            document.getElementById("badge").textContent = "DEMO";
        } else {
            document.getElementById("demoBanner").style.display = "none";
            document.getElementById("badge").textContent = `${allItems.length} events`;
        }

        document.getElementById("errorBanner").style.display = "none";
        populateRoomFilter();
        render();

        const now = new Date();
        document.getElementById("lastRefresh").textContent =
            `Updated ${now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;

    } catch (err) {
        console.error(err);
        document.getElementById("errorBanner").textContent = `Failed to load: ${err.message}`;
        document.getElementById("errorBanner").style.display = "block";
    }
}

// ── Filtering ──────────────────────────────
function getFiltered() {
    return allItems.filter(item => {
        if (activeStatusFilter !== "all" && item.status !== activeStatusFilter) return false;
        if (activeRoomFilter !== "all" && item.room !== activeRoomFilter) return false;
        return true;
    });
}

function populateRoomFilter() {
    const rooms = [...new Set(allItems.map(i => i.room).filter(Boolean))].sort();
    const sel = document.getElementById("roomFilter");
    const current = sel.value;
    sel.innerHTML = '<option value="all">All Rooms</option>';
    rooms.forEach(r => {
        const opt = document.createElement("option");
        opt.value = r;
        opt.textContent = r;
        sel.appendChild(opt);
    });
    sel.value = rooms.includes(current) ? current : "all";
    activeRoomFilter = sel.value;
}

// ── Rendering ──────────────────────────────
function render() {
    const items = getFiltered();
    renderStats(items);
    renderCalendar(items);
    renderUpcoming(items);
    renderRooms(items);
}

function renderStats(items) {
    const confirmed = items.filter(i => i.status === "confirmed" || i.status === "definite").length;
    const tentative = items.filter(i => i.status === "tentative" || i.status === "prospect").length;
    const guests = items.reduce((sum, i) => sum + (parseInt(i.guest_count) || 0), 0);
    const rooms = new Set(items.map(i => i.room).filter(Boolean)).size;

    document.getElementById("statTotal").textContent = items.length;
    document.getElementById("statConfirmed").textContent = confirmed;
    document.getElementById("statTentative").textContent = tentative;
    document.getElementById("statGuests").textContent = guests.toLocaleString();
    document.getElementById("statRooms").textContent = rooms;
}

function renderCalendar(items) {
    const { start } = getWeekRange(weekOffset);
    const today = fmt(new Date());

    // Group by day
    const grouped = {};
    for (let i = 0; i < 7; i++) {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        grouped[fmt(d)] = [];
    }
    items.forEach(item => {
        const key = (item.start || "").slice(0, 10);
        if (grouped[key]) grouped[key].push(item);
    });

    let html = '<div class="calendar">';
    const dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

    for (let i = 0; i < 7; i++) {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        const key = fmt(d);
        const isToday = key === today;
        const dayItems = grouped[key] || [];
        dayItems.sort((a, b) => (a.start || "").localeCompare(b.start || ""));

        html += `<div class="day-col${isToday ? ' today' : ''}">`;
        html += `<div class="day-head">`;
        html += `<div class="dname">${dayNames[i]}</div>`;
        html += `<div class="ddate">${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</div>`;
        html += `<div class="dcount">${dayItems.length} event${dayItems.length !== 1 ? "s" : ""}</div>`;
        html += `</div><div class="day-body">`;

        if (dayItems.length === 0) {
            html += '<div class="empty">No events</div>';
        } else {
            dayItems.forEach(item => {
                const typeClass = item.type || "event";
                const statusClass = (item.status || "").replace(/\s+/g, "-");
                const timeStr = fmtTime(item.start);
                const endStr = fmtTime(item.end);
                const timeDisplay = endStr ? `${timeStr} – ${endStr}` : timeStr;

                html += `<div class="ev-card ${typeClass}">`;
                html += `<div class="ev-badges">`;
                html += `<span class="type-tag ${typeClass}">${escapeHtml(typeClass)}</span>`;
                if (item.status) {
                    html += `<span class="status-tag ${statusClass}">${escapeHtml(item.status)}</span>`;
                }
                html += `</div>`;
                html += `<div class="ev-name">${escapeHtml(item.name)}</div>`;
                html += `<div class="ev-time">${timeDisplay}</div>`;
                if (item.room) html += `<div class="ev-meta">${escapeHtml(item.room)}</div>`;
                if (item.contact) html += `<div class="ev-meta">${escapeHtml(item.contact)}</div>`;
                if (item.guest_count) html += `<div class="ev-meta">${item.guest_count} guests</div>`;
                html += `</div>`;
            });
        }

        html += `</div></div>`;
    }

    html += "</div>";
    document.getElementById("calendarContainer").innerHTML = html;
}

function renderUpcoming(items) {
    const now = new Date().toISOString();
    const upcoming = items
        .filter(i => (i.start || "") >= now.slice(0, 10))
        .sort((a, b) => (a.start || "").localeCompare(b.start || ""))
        .slice(0, 20);

    const tbody = document.getElementById("upcomingBody");

    if (upcoming.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#aaa;padding:24px;">No upcoming events this week</td></tr>';
        return;
    }

    tbody.innerHTML = upcoming.map(item => {
        const statusClass = (item.status || "").replace(/\s+/g, "-");
        return `<tr>
            <td>${fmtDate(item.start)}</td>
            <td>${fmtTime(item.start)}${item.end ? " – " + fmtTime(item.end) : ""}</td>
            <td class="name-cell">${escapeHtml(item.name)}</td>
            <td><span class="status-tag ${statusClass}">${escapeHtml(item.status || "—")}</span></td>
            <td>${escapeHtml(item.room || "—")}</td>
            <td>${escapeHtml(item.contact || "—")}</td>
            <td>${item.guest_count || "—"}</td>
        </tr>`;
    }).join("");
}

function renderRooms(items) {
    const rooms = {};
    items.forEach(item => {
        if (item.room) rooms[item.room] = (rooms[item.room] || 0) + 1;
    });

    const sorted = Object.entries(rooms).sort((a, b) => b[1] - a[1]);
    const grid = document.getElementById("roomsGrid");

    if (sorted.length === 0) {
        grid.innerHTML = '<div style="color:#aaa;font-size:14px;">No room data</div>';
        return;
    }

    grid.innerHTML = sorted.map(([name, count]) =>
        `<div class="room-card">
            <span class="room-name">${escapeHtml(name)}</span>
            <span class="room-count">${count}</span>
        </div>`
    ).join("");
}

// ── Navigation & Filters ───────────────────
function changeWeek(dir) {
    if (dir === 0) weekOffset = 0;
    else weekOffset += dir;
    refreshData();
}

document.getElementById("statusFilter").addEventListener("change", function() {
    activeStatusFilter = this.value;
    render();
});

document.getElementById("roomFilter").addEventListener("change", function() {
    activeRoomFilter = this.value;
    render();
});

// ── Init ───────────────────────────────────
refreshData();

// Auto-refresh every 5 minutes
refreshTimer = setInterval(refreshData, 5 * 60 * 1000);
</script>
</body>
</html>"""


# ── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tripleseat Team Dashboard")
    parser.add_argument("--port", type=int, default=5050, help="Port (default 5050)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host (default 0.0.0.0)")
    parser.add_argument("--demo", action="store_true", help="Use sample data instead of API")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    global _demo_mode
    _demo_mode = args.demo

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    if not _demo_mode:
        ck = os.environ.get("TRIPLESEAT_CONSUMER_KEY", "")
        cs = os.environ.get("TRIPLESEAT_CONSUMER_SECRET", "")
        if not ck or not cs:
            print("WARNING: No API credentials found.")
            print("  Set TRIPLESEAT_CONSUMER_KEY and TRIPLESEAT_CONSUMER_SECRET in .env")
            print("  Or run with --demo to use sample data.\n")

    print(f"\n  Tripleseat Dashboard")
    print(f"  {'DEMO MODE' if _demo_mode else 'LIVE MODE'}")
    print(f"  http://localhost:{args.port}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
