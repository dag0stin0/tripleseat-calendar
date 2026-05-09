"""
Vercel Serverless Function — /api/events

Reads the latest Tripleseat snapshot from Vercel Blob (written by
/api/cron/sync). Falls back to CSV if the snapshot is unreachable.

Query params:
    start   YYYY-MM-DD (inclusive)
    end     YYYY-MM-DD (inclusive)
    source  csv | blob  (optional override for debugging)
"""

import csv
import json
import logging
import os
import re
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import requests

logger = logging.getLogger(__name__)

EVENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "events")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SNAPSHOT_PATH = "tripleseat/events.json"
SNAPSHOT_TIMEOUT = 8


def _parse_money(v):
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


def _parse_csv_time(date_str, time_str):
    if not date_str or not time_str:
        return ""
    try:
        return datetime.strptime(
            f"{date_str} {time_str}", "%m/%d/%Y %I:%M %p"
        ).strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return ""


def _loc_key(location):
    return "dc" if "dc" in (location or "").lower() else "nyc"


def load_csv_events():
    items = []
    if not os.path.isdir(EVENTS_DIR):
        return items

    event_id = 1
    for filename in sorted(f for f in os.listdir(EVENTS_DIR) if f.endswith(".csv")):
        filepath = os.path.join(EVENTS_DIR, filename)
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
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


def load_blob_snapshot():
    """List blobs at the snapshot prefix, fetch the most recent one.

    Vercel Blob appends a random suffix to uploaded paths, so we can't
    construct a deterministic URL — list and pick the newest instead.

    Returns (items, fetched_at, error).
    """
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        return [], None, "no_blob_token"
    try:
        list_resp = requests.get(
            "https://blob.vercel-storage.com",
            params={"prefix": SNAPSHOT_PATH.rsplit(".", 1)[0], "limit": "100"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=SNAPSHOT_TIMEOUT,
        )
        list_resp.raise_for_status()
        blobs = list_resp.json().get("blobs", [])
        if not blobs:
            return [], None, "snapshot_not_found"

        latest = max(blobs, key=lambda b: b.get("uploadedAt", ""))
        data_resp = requests.get(latest["url"], timeout=SNAPSHOT_TIMEOUT)
        data_resp.raise_for_status()
        payload = data_resp.json()
        return payload.get("items", []), payload.get("uploadedAt") or latest.get("uploadedAt"), None
    except Exception as e:
        logger.exception("blob fetch failed")
        return [], None, f"blob_fetch_failed: {e}"


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

        if not start_str:
            start_str = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")
        if not end_str:
            end_str = (datetime.utcnow() + timedelta(days=365)).strftime("%Y-%m-%d")

        items = []
        source = "csv"
        fetched_at = None
        notes = []

        if source_override != "csv":
            blob_items, blob_fetched_at, blob_err = load_blob_snapshot()
            if blob_items:
                items = blob_items
                source = "blob"
                fetched_at = blob_fetched_at
            elif source_override == "blob":
                return self._send_json(502, {"error": f"Blob unavailable: {blob_err}"})
            elif blob_err:
                notes.append(f"blob_fallback: {blob_err}")

        if not items:
            try:
                items = load_csv_events()
            except Exception as e:
                logger.exception("CSV load failed")
                return self._send_json(500, {"error": str(e)})

        items = [i for i in items if (i.get("status") or "").lower() != "lost"]

        if start_str and end_str:
            items = [
                i for i in items
                if i.get("start") and start_str <= i["start"][:10] <= end_str
            ]

        items.sort(key=lambda x: x.get("start", ""))

        payload = {
            "items": items,
            "count": len(items),
            "source": source,
            "served_at": datetime.utcnow().isoformat() + "Z",
        }
        if fetched_at:
            payload["snapshot_fetched_at"] = fetched_at
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
