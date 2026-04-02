#!/usr/bin/env python3
"""
Tripleseat Weekly Calendar Generator
=====================================
Pulls events and bookings from your Tripleseat account and generates
a clean HTML weekly calendar you can share with your team.

Setup:
  1. Copy .env.example to .env and fill in your credentials
  2. pip install requests requests-oauthlib
  3. python generate_calendar.py

Options:
  --week-offset N    Generate for N weeks from now (0=this week, 1=next, -1=last)
  --output PATH      Custom output file path
  --title TEXT        Custom calendar title
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Load .env file if present
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

from tripleseat_client import TripleseatClient
from calendar_builder import build_calendar_html, get_week_range


def load_config():
    """Load configuration from environment variables."""
    consumer_key = os.environ.get("TRIPLESEAT_CONSUMER_KEY", "")
    consumer_secret = os.environ.get("TRIPLESEAT_CONSUMER_SECRET", "")
    api_key = os.environ.get("TRIPLESEAT_API_KEY", "")

    if not consumer_key or not consumer_secret:
        print("ERROR: Missing credentials.")
        print("Set TRIPLESEAT_CONSUMER_KEY and TRIPLESEAT_CONSUMER_SECRET")
        print("in your .env file or as environment variables.")
        print()
        print("See .env.example for the template.")
        sys.exit(1)

    return {
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret,
        "api_key": api_key or None,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate weekly calendar from Tripleseat")
    parser.add_argument("--week-offset", type=int, default=0,
                        help="Week offset from current (0=this week, 1=next, -1=last)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output HTML file path")
    parser.add_argument("--title", type=str, default="Weekly Event Calendar",
                        help="Calendar title")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")
    parser.add_argument("--demo", action="store_true",
                        help="Generate with sample data (no API call)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    # Calculate week range
    reference = datetime.now() + timedelta(weeks=args.week_offset)
    week_start, week_end = get_week_range(reference)
    logging.info(f"Generating calendar for: {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}")

    if args.demo:
        events, bookings = generate_sample_data(week_start)
    else:
        config = load_config()
        client = TripleseatClient(
            consumer_key=config["consumer_key"],
            consumer_secret=config["consumer_secret"],
            api_key=config["api_key"],
        )

        logging.info("Fetching events from Tripleseat...")
        try:
            events = client.search_events(
                start_date=week_start.strftime("%Y-%m-%d"),
                end_date=week_end.strftime("%Y-%m-%d"),
            )
        except Exception as e:
            logging.warning(f"Event search failed ({e}), trying full event list...")
            events = client.get_events()

        logging.info(f"Fetched {len(events)} events")

        logging.info("Fetching bookings from Tripleseat...")
        try:
            bookings = client.search_bookings(
                start_date=week_start.strftime("%Y-%m-%d"),
                end_date=week_end.strftime("%Y-%m-%d"),
            )
        except Exception as e:
            logging.warning(f"Booking search failed ({e}), trying full booking list...")
            bookings = client.get_bookings()

        logging.info(f"Fetched {len(bookings)} bookings")

    # Build HTML
    html = build_calendar_html(
        events=events,
        bookings=bookings,
        week_start=week_start,
        week_end=week_end,
        title=args.title,
    )

    # Write output
    if args.output:
        output_path = Path(args.output)
    else:
        date_slug = week_start.strftime("%Y-%m-%d")
        output_path = Path(__file__).parent / f"calendar_{date_slug}.html"

    output_path.write_text(html, encoding="utf-8")
    logging.info(f"Calendar saved to: {output_path}")
    print(f"\n✅ Calendar generated: {output_path}")
    print(f"   Open in your browser to view and print/share.")


def generate_sample_data(week_start):
    """Generate realistic sample data for demo mode."""
    from datetime import time as dtime

    sample_events = []
    sample_bookings = []

    names = [
        ("Johnson Wedding Reception", "confirmed", "Grand Ballroom", "Sarah Johnson", 150),
        ("Tech Corp Annual Dinner", "confirmed", "Rooftop Terrace", "Mike Chen", 80),
        ("Birthday Celebration — Martinez", "tentative", "Private Dining Room", "Ana Martinez", 35),
        ("Charity Gala 2026", "confirmed", "Grand Ballroom", "David Park", 200),
        ("Corporate Lunch — Acme Inc", "prospect", "Garden Room", "Lisa Wong", 25),
        ("Rehearsal Dinner — Kim/Patel", "confirmed", "Wine Cellar", "Priya Patel", 40),
        ("Sunday Brunch — Book Club", "tentative", "Patio", "Rachel Green", 15),
        ("Product Launch Happy Hour", "confirmed", "Lounge Bar", "Tom Baker", 60),
        ("Staff Training Lunch", "confirmed", "Conference Room A", "HR Team", 30),
        ("Wine Tasting Evening", "tentative", "Wine Cellar", "James Noir", 20),
    ]

    times = [
        (10, 0, 14, 0), (18, 0, 22, 0), (12, 0, 15, 0),
        (17, 0, 23, 0), (11, 30, 13, 30), (18, 30, 21, 0),
        (10, 0, 12, 0), (17, 0, 20, 0), (12, 0, 13, 30),
        (19, 0, 21, 30),
    ]

    days_used = [0, 1, 2, 2, 3, 4, 6, 3, 1, 5]  # Mon=0 ... Sun=6

    for i, (name, status, room, contact, guests) in enumerate(names):
        day_offset = days_used[i]
        sh, sm, eh, em = times[i]
        start = (week_start + timedelta(days=day_offset)).replace(
            hour=sh, minute=sm, second=0, microsecond=0)
        end = (week_start + timedelta(days=day_offset)).replace(
            hour=eh, minute=em, second=0, microsecond=0)

        entry = {
            "id": 1000 + i,
            "name": name,
            "status": status,
            "event_start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_end": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "location_name": "The Grand Venue",
            "room_name": room,
            "contact_name": contact,
            "guest_count": guests,
        }

        if i % 3 == 0:
            # Make some bookings instead of events
            entry["booking_start"] = entry.pop("event_start")
            entry["booking_end"] = entry.pop("event_end")
            entry["booking_name"] = entry.pop("name")
            entry["booking_status"] = entry.pop("status")
            sample_bookings.append(entry)
        else:
            entry["event_name"] = entry.pop("name")
            entry["event_status"] = entry.pop("status")
            sample_events.append(entry)

    return sample_events, sample_bookings


if __name__ == "__main__":
    main()
