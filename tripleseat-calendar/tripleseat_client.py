"""
Tripleseat API Client — OAuth 1.0 Authentication
Handles authentication, pagination, and rate limiting for the Tripleseat API.

NOTE: OAuth 1.0 is deprecated and will be shut off July 1, 2026.
      Migrate to OAuth 2.0 before then. See:
      https://support.tripleseat.com/hc/en-us/articles/35211389645079
"""

import time
import logging
from datetime import datetime, timedelta
from requests_oauthlib import OAuth1Session

logger = logging.getLogger(__name__)

API_BASE = "https://api.tripleseat.com/v1"
RATE_LIMIT_PER_SECOND = 10
REQUEST_INTERVAL = 1.0 / RATE_LIMIT_PER_SECOND  # 0.1s between requests


class TripleseatClient:
    def __init__(self, consumer_key: str, consumer_secret: str,
                 api_key: str = None, format: str = "json"):
        """
        Initialize the Tripleseat API client.

        Args:
            consumer_key: Your OAuth 1.0 consumer key
            consumer_secret: Your OAuth 1.0 consumer secret
            api_key: Optional API key (some accounts use this)
            format: Response format — 'json' or 'xml'
        """
        self.session = OAuth1Session(
            client_key=consumer_key,
            client_secret=consumer_secret,
        )
        self.api_key = api_key
        self.format = format
        self._last_request_time = 0

    def _rate_limit(self):
        """Enforce 10 requests/second rate limit."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """
        Make a rate-limited GET request to the Tripleseat API.

        Args:
            endpoint: API path (e.g. '/events')
            params: Query parameters

        Returns:
            Parsed JSON response
        """
        self._rate_limit()

        url = f"{API_BASE}{endpoint}.{self.format}"
        params = params or {}
        if self.api_key:
            params["api_key"] = self.api_key

        logger.debug(f"GET {url} params={params}")

        response = self.session.get(url, params=params, timeout=30)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 5))
            logger.warning(f"Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            return self._request(endpoint, params)

        response.raise_for_status()
        return response.json()

    def _fetch_all_pages(self, endpoint: str, params: dict = None,
                         max_pages: int = 50) -> list:
        """
        Fetch all pages from a paginated endpoint.

        Args:
            endpoint: API path
            params: Query parameters
            max_pages: Safety limit on pages to fetch

        Returns:
            Combined list of all results
        """
        params = params or {}
        all_results = []
        page = 1

        while page <= max_pages:
            params["page"] = page
            data = self._request(endpoint, params)

            # Tripleseat returns the resource name as the key
            # e.g. {"results": [...]} or {"events": [...]}
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
            logger.info(f"Page {page}: fetched {len(results)} records")

            # If we got fewer results than expected, we're on the last page
            if len(results) < 25:  # Tripleseat default page size
                break

            page += 1

        return all_results

    # ── Events ──────────────────────────────────────────────

    def get_events(self, **kwargs) -> list:
        """Get all events (paginated)."""
        return self._fetch_all_pages("/events", kwargs)

    def get_event(self, event_id: int) -> dict:
        """Get a single event by ID."""
        return self._request(f"/events/{event_id}")

    def search_events(self, **kwargs) -> list:
        """
        Search events with query parameters.

        Common params:
            query: Search string
            start_date: Filter by start date (YYYY-MM-DD)
            end_date: Filter by end date (YYYY-MM-DD)
            order: Field to order by (e.g. 'event_start')
            sort_direction: 'asc' or 'desc'
        """
        return self._fetch_all_pages("/events/search", kwargs)

    # ── Bookings ────────────────────────────────────────────

    def get_bookings(self, **kwargs) -> list:
        """Get all bookings (paginated)."""
        return self._fetch_all_pages("/bookings", kwargs)

    def get_booking(self, booking_id: int) -> dict:
        """Get a single booking by ID."""
        return self._request(f"/bookings/{booking_id}")

    def search_bookings(self, **kwargs) -> list:
        """
        Search bookings with query parameters.

        Common params:
            query: Search string
            start_date: Filter by start date
            end_date: Filter by end date
        """
        return self._fetch_all_pages("/bookings/search", kwargs)

    # ── Leads ───────────────────────────────────────────────

    def get_leads(self, **kwargs) -> list:
        """Get all leads (paginated)."""
        return self._fetch_all_pages("/leads", kwargs)

    def search_leads(self, **kwargs) -> list:
        """Search leads with query parameters."""
        return self._fetch_all_pages("/leads/search", kwargs)

    # ── Contacts ────────────────────────────────────────────

    def get_contacts(self, **kwargs) -> list:
        """Get all contacts (paginated)."""
        return self._fetch_all_pages("/contacts", kwargs)

    # ── Sites & Locations ───────────────────────────────────

    def get_sites(self) -> list:
        """Get all sites."""
        return self._fetch_all_pages("/sites")

    def get_locations(self, site_id: int = None) -> list:
        """Get all locations, optionally filtered by site."""
        params = {}
        if site_id:
            params["site_id"] = site_id
        return self._fetch_all_pages("/locations", params)

    # ── Users ───────────────────────────────────────────────

    def get_users(self) -> list:
        """Get all users."""
        return self._fetch_all_pages("/users")
