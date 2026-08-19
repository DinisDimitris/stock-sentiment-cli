"""StockTwits ingestion — finance-specific social media."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ingestion.base_source import BaseSource

logger = logging.getLogger(__name__)
BASE_URL = "https://api.stocktwits.com/api/2"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://stocktwits.com/",
}


class StockTwitsSource(BaseSource):
    source_name = "stocktwits"

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        url = f"{BASE_URL}/streams/symbol/{ticker}.json"
        async with httpx.AsyncClient(timeout=10, headers=BROWSER_HEADERS) as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                return r.json().get("messages", [])
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    logger.warning("[stocktwits] 403 from %s using browser-like headers; source may be blocking automated clients for %s", url, ticker)
                raise

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        pub_at = None
        if raw_item.get("created_at"):
            try:
                pub_at = datetime.fromisoformat(
                    raw_item["created_at"].replace("Z", "+00:00")
                )
            except Exception:
                pass

        msg_id = raw_item.get("id", "")
        user = raw_item.get("user", {})
        return {
            "url": f"https://stocktwits.com/message/{msg_id}",
            "title": raw_item.get("body", "")[:100],
            "body": raw_item.get("body", ""),
            "published_at": pub_at,
            "source_subtype": "stocktwits_post",
            "fast_lane": False,
        }
