"""
SEC EDGAR ingestion via the EDGAR full-text search API.
Polls for new filings matching a ticker. 8-K triggers fast lane.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ingestion.base_source import BaseSource

logger = logging.getLogger(__name__)

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
FAST_LANE_TYPES = {"8-K", "13D", "13G"}
TARGET_SUBTYPES = {"8-K", "10-Q", "10-K", "DEF 14A", "13D", "13G"}

HEADERS = {"User-Agent": "StockSentimentBot admin@example.com"}


class SecEdgarSource(BaseSource):
    source_name = "sec_edgar"

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        results = []
        for form_type in TARGET_SUBTYPES:
            params = {
                "q": f'"{ticker}"',
                "forms": form_type,
                "dateRange": "custom",
                "startdt": "2024-01-01",
                "hits.hits.total.value": 10,
            }
            async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
                r = await client.get(EDGAR_SEARCH_URL, params=params)
                r.raise_for_status()
                hits = r.json().get("hits", {}).get("hits", [])
                for hit in hits:
                    hit["_form_type"] = form_type
                results.extend(hits)
        return results

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        src = raw_item.get("_source", {})
        form_type = raw_item.get("_form_type", "unknown")
        filed = src.get("file_date", "")
        pub_at = None
        if filed:
            try:
                pub_at = datetime.fromisoformat(filed).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        url = src.get("file_url", "") or src.get("biz_location", "")
        return {
            "url": url or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={src.get('entity_id','')}&type={form_type}",
            "title": f"{form_type}: {src.get('display_names', [''])[0] if src.get('display_names') else ''}",
            "body": src.get("file_description", "") or src.get("period_of_report", ""),
            "published_at": pub_at,
            "source_subtype": form_type,
            "fast_lane": form_type in FAST_LANE_TYPES,
        }
