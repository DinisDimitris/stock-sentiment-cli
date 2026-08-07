"""
Company investor relations RSS ingestion.
Maintains a per-ticker RSS URL registry. Easily extensible.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from email.utils import parsedate_to_datetime

import feedparser

from ingestion.base_source import BaseSource

logger = logging.getLogger(__name__)

# Curated IR RSS feeds for major companies. Extend as new companies are watched.
IR_RSS_REGISTRY: dict[str, str] = {
    "AAPL": "https://www.apple.com/newsroom/rss-feed.rss",
    "MSFT": "https://news.microsoft.com/feed/",
    "GOOGL": "https://blog.google/rss/",
    "AMZN": "https://ir.aboutamazon.com/rss/news-releases.xml",
    "NVDA": "https://nvidianews.nvidia.com/news/latest/rss",
    "META": "https://investor.fb.com/rss/news-releases.xml",
    "TSLA": "https://ir.tesla.com/rss/news-releases.xml",
    "NFLX": "https://ir.netflix.net/ir/doc/rss.xml",
    "AMD": "https://ir.amd.com/news-releases/rss",
    "INTC": "https://newsroom.intel.com/feed/",
}


class CompanyIRSource(BaseSource):
    source_name = "company_ir"

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        rss_url = IR_RSS_REGISTRY.get(ticker.upper())
        if not rss_url:
            return []
        # feedparser is sync; run in executor to avoid blocking event loop
        import asyncio
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, rss_url)
        return [{"_ticker": ticker, **entry} for entry in feed.entries[:20]]

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
            "source_subtype": "press_release",
            "fast_lane": False,
        }
