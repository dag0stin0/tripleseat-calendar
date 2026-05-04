"""
Vercel Cron — /api/cron/sync

Pulls all Tripleseat events for a rolling window, normalizes them, and writes
a single JSON snapshot to Vercel Blob at `tripleseat/events.json`. The public
read endpoint (/api/events) reads this snapshot instead of hitting Tripleseat
on every request — that pattern was timing out the lambda.

Auth: Vercel cron sends `Authorization: Bearer <CRON_SECRET>`. We require it
to match the env var so the endpoint can't be drained by random callers.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tripleseat_client import TripleseatClient  # noqa: E402

logger = logging.getLogger(__name__)

WINDOW_PAST_DAYS = 60
WINDOW_FUTURE_DAYS = 365
MAX_PAGES = 30
SNAPSHOT_PATH = "tripleseat/events.json"


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


def _as_str(v):
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
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %I:%M%p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y %I:%M %p",
    "%m-%d-%Y",
)


def _ts_iso(v, time_hint=None):
    if not v:
        return ""
    s = str(v).strip()
    if not s:
        return ""
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
    return ""


def _loc_key(location):
    return "dc" if "dc" in (location or "").lower() else "nyc"


def _ts_contact(raw):
    c = raw.get("contact") or raw.get("booking_contact") or raw.get("lead_contact") or {}
    if isinstance(c, dict):
        first = _as_str(c.get("first_name"))
        last = _as_str(c.get("last_name"))
        joined = (first + " " + last).strip()
        return joined or _as_str(c.get("name")) or _as_str(c.get("full_name")) or ""
    return _as_str(c)


def _ts_map_event(raw, eid):
    location = (
        _as_str(raw.get("site_name"))
        or _as_str(raw.get("location_name"))
        or _as_str(raw.get("site"))
        or _as_str(raw.get("location"))
    )
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
            raw.get("event_start") or raw.get("start_time") or raw.get("start_date")
            or raw.get("event_date") or raw.get("date"),
            time_hint=raw.get("start_time_only") or raw.get("event_start_time"),
        ),
        "end": _ts_iso(
            raw.get("event_end") or raw.get("end_time") or raw.get("end_date")
            or raw.get("event_date") or raw.get("date"),
            time_hint=raw.get("end_time_only") or raw.get("event_end_time"),
        ),
        "location": location,
        "locKey": _loc_key(location),
        "room": rooms,
        "contact": contact,
        "guest_count": guest_count,
        "event_style": event_style,
        "fb_min": _parse_money(raw.get("food_beverage_minimum") or raw.get("fb_min")),
        "grand_total": _parse_money(raw.get("grand_total") or raw.get("total")),
        "deposit": _parse_money(raw.get("deposit")),
        "amount_due": _parse_money(raw.get("amount_due") or raw.get("balance_due")),
        "actual": _parse_money(raw.get("actual_revenue") or raw.get("actual")),
    }


def fetch_tripleseat_snapshot():
    ck = os.environ.get("TRIPLESEAT_CONSUMER_KEY")
    cs = os.environ.get("TRIPLESEAT_CONSUMER_SECRET")
    api = os.environ.get("TRIPLESEAT_API_KEY")
    if not (ck and cs):
        raise RuntimeError("TRIPLESEAT_CONSUMER_KEY and TRIPLESEAT_CONSUMER_SECRET required")

    client = TripleseatClient(consumer_key=ck, consumer_secret=cs, api_key=api)
    raw_events = client.get_events(max_pages=MAX_PAGES) or []

    items = []
    skipped = 0
    for idx, r in enumerate(raw_events):
        try:
            mapped = _ts_map_event(r, idx + 1)
            if mapped["start"]:
                items.append(mapped)
            else:
                skipped += 1
        except Exception as e:
            logger.warning("Skipping Tripleseat record %s: %s", idx, e)
            skipped += 1

    items.sort(key=lambda x: x.get("start", ""))

    today = datetime.utcnow()
    return {
        "fetched_at": today.isoformat() + "Z",
        "window": {
            "start": (today - timedelta(days=WINDOW_PAST_DAYS)).strftime("%Y-%m-%d"),
            "end": (today + timedelta(days=WINDOW_FUTURE_DAYS)).strftime("%Y-%m-%d"),
        },
        "count": len(items),
        "skipped": skipped,
        "items": items,
    }


def upload_to_blob(payload):
    """PUT the snapshot to Vercel Blob, then delete prior versions.

    Vercel Blob always appends a random suffix to uploaded paths
    (the addRandomSuffix=false / allowOverwrite options aren't honored
    over the raw HTTP API), so we instead let it create a new file each
    run and prune older versions at the same prefix.

    Returns the public URL of the new object.
    """
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN env var not set")

    body = json.dumps(payload, default=str).encode("utf-8")
    put = requests.put(
        f"https://blob.vercel-storage.com/{SNAPSHOT_PATH}",
        headers={
            "Authorization": f"Bearer {token}",
            "x-content-type": "application/json",
            "x-cache-control-max-age": "60",
        },
        data=body,
        timeout=30,
    )
    put.raise_for_status()
    new_url = put.json().get("url", "")

    _prune_old_snapshots(token, keep_url=new_url)
    return new_url


def _prune_old_snapshots(token, keep_url):
    """Delete every blob at the snapshot prefix except the one we just wrote."""
    try:
        prefix = SNAPSHOT_PATH.rsplit(".", 1)[0]
        listing = requests.get(
            "https://blob.vercel-storage.com",
            params={"prefix": prefix, "limit": "100"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        listing.raise_for_status()
        stale = [b["url"] for b in listing.json().get("blobs", []) if b.get("url") and b["url"] != keep_url]
        if not stale:
            return
        requests.post(
            "https://blob.vercel-storage.com/delete",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"urls": stale},
            timeout=15,
        )
    except Exception as e:
        logger.warning("prune failed (non-fatal): %s", e)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Vercel cron auth: header is "Authorization: Bearer <CRON_SECRET>"
        secret = os.environ.get("CRON_SECRET")
        auth = self.headers.get("Authorization", "")
        if secret and auth != f"Bearer {secret}":
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            snapshot = fetch_tripleseat_snapshot()
            blob_url = upload_to_blob(snapshot)
            self._send_json(200, {
                "ok": True,
                "count": snapshot["count"],
                "skipped": snapshot["skipped"],
                "url": blob_url,
                "fetched_at": snapshot["fetched_at"],
            })
        except Exception as e:
            logger.exception("sync failed")
            self._send_json(500, {"ok": False, "error": str(e)})

    def _send_json(self, status, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
