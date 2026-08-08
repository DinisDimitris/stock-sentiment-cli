"""
Yahoo Finance RSS ingestion. One feed URL per ticker.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from ingestion.base_source import BaseSource

logger = logging.getLogger(__name__)

YAHOO_RSS_TEMPLATE = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


class YahooFinanceSource(BaseSource):
    source_name = "yahoo_finance"

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        url = YAHOO_RSS_TEMPLATE.format(ticker=ticker)
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, url)
        return [{"_ticker": ticker, **entry} for entry in feed.entries[:30]]

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        pub_at = None
        if raw_item.get("published"):
            try:
                pub_at = parsedate_to_datetime(raw_item["published"])
            except Exception:
                pass

        return {
            "url": raw_item.get("link", ""),
            "title": raw_item.get("title", ""),
            "body": raw_item.get("summary", "") or raw_item.get("description", ""),
            "published_at": pub_at,
            "source_subtype": "news",
            "fast_lane": False,
        }
