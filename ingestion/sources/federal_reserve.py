"""Federal Reserve RSS feeds — FOMC statements, speeches, meeting minutes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from ingestion.base_source import BaseSource

logger = logging.getLogger(__name__)

FED_RSS_FEEDS = [
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://www.federalreserve.gov/feeds/speeches.xml",
]


class FederalReserveSource(BaseSource):
    source_name = "federal_reserve"

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        # Fed data is macro — not ticker-specific but ingest for all tickers
        loop = asyncio.get_event_loop()
        results = []
        for feed_url in FED_RSS_FEEDS:
            feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
            results.extend(feed.entries[:20])
        return results

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        pub_at = None
        if raw_item.get("published"):
            try:
                pub_at = parsedate_to_datetime(raw_item["published"])
            except Exception:
                pass

        subtype = "speech"
        title = raw_item.get("title", "")
        if any(kw in title.lower() for kw in ["fomc", "minutes", "statement"]):
            subtype = "fomc"

        return {
            "url": raw_item.get("link", ""),
            "title": title,
            "body": raw_item.get("summary", "") or raw_item.get("description", ""),
            "published_at": pub_at,
            "source_subtype": subtype,
            "fast_lane": False,
        }
