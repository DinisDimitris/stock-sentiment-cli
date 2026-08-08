"""
Finnhub ingestion: general news and earnings call transcripts.
Respects free tier: max 60 calls/min → 1 call/sec enforced here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from config.settings import settings
from ingestion.base_source import BaseSource

logger = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1"
_last_call_time: float = 0.0


async def _rate_limited_get(url: str, params: dict) -> dict:
    global _last_call_time
    elapsed = time.monotonic() - _last_call_time
    if elapsed < 1.05:
        await asyncio.sleep(1.05 - elapsed)
    _last_call_time = time.monotonic()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


class FinnhubNewsSource(BaseSource):
    source_name = "finnhub_news"

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        if not settings.finnhub_key:
            return []
        data = await _rate_limited_get(
            f"{BASE_URL}/company-news",
            {"symbol": ticker, "from": "2024-01-01", "to": "2099-12-31", "token": settings.finnhub_key},
        )
        return data[:50] if isinstance(data, list) else []

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        pub_at = None
        if raw_item.get("datetime"):
            pub_at = datetime.fromtimestamp(raw_item["datetime"], tz=timezone.utc)

        is_major = raw_item.get("category", "") == "major"
        return {
            "url": raw_item.get("url", ""),
            "title": raw_item.get("headline", ""),
            "body": raw_item.get("summary", ""),
            "published_at": pub_at,
            "source_subtype": "major_news" if is_major else "news",
            "fast_lane": is_major,
            "raw_json": raw_item,
        }


class FinnhubTranscriptSource(BaseSource):
    source_name = "finnhub_transcripts"

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        if not settings.finnhub_key:
            return []
        # Get list of available transcripts
        listing = await _rate_limited_get(
            f"{BASE_URL}/stock/transcripts/list",
            {"symbol": ticker, "token": settings.finnhub_key},
        )
        transcripts = listing.get("transcripts", [])[:3]  # last 3 quarters
        results = []
        for t in transcripts:
            detail = await _rate_limited_get(
                f"{BASE_URL}/stock/transcripts",
                {"id": t.get("id", ""), "token": settings.finnhub_key},
            )
            detail["_meta"] = t
            results.append(detail)
        return results

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        meta = raw_item.get("_meta", {})
        pub_at = None
        if meta.get("time"):
            try:
                pub_at = datetime.fromisoformat(meta["time"].replace("Z", "+00:00"))
            except Exception:
                pass

        # Flatten transcript content into body text
        content_blocks = raw_item.get("transcript", [])
        body_parts = []
        for block in content_blocks:
            for speech in block.get("speech", []):
                body_parts.append(f"{speech.get('name', '')}: {speech.get('transcript', '')}")
        body = "\n\n".join(body_parts)

        return {
            "url": f"https://finnhub.io/transcripts/{meta.get('id', '')}",
            "title": f"Earnings Call: {meta.get('title', '')}",
            "body": body,
            "published_at": pub_at,
            "source_subtype": "earnings_call",
            "fast_lane": False,
        }
