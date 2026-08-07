"""
FRED API ingestion — macroeconomic indicators.
Stores to macro_indicators table (NOT raw_documents / FinBERT pipeline).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)
BASE_URL = "https://api.stlouisfed.org/fred"

# Key indicators tracked per the sector_macro_weights config
INDICATORS = {
    "DFF": "Federal Funds Effective Rate",
    "CPIAUCSL": "Consumer Price Index",
    "UNRATE": "Unemployment Rate",
    "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury",
    "VIXCLS": "CBOE Volatility Index",
    "INDPRO": "Industrial Production Index",
    "DCOILWTICO": "WTI Crude Oil Price",
}


async def fetch_and_store_indicators() -> None:
    if not settings.fred_api_key:
        logger.warning("[fred] No FRED_API_KEY configured; skipping macro data.")
        return

    from db.session import AsyncSessionLocal
    import sqlalchemy as sa

    async with AsyncSessionLocal() as session:
        for code, name in INDICATORS.items():
            try:
                data = await _fetch_series(code)
                observations = data.get("observations", [])
                for obs in observations[-90:]:  # last 90 data points
                    if obs.get("value") == ".":
                        continue
                    released_at = datetime.fromisoformat(obs["date"]).replace(tzinfo=timezone.utc)
                    # Upsert via raw SQL to avoid conflict on existing data
                    await session.execute(
                        sa.text("""
                            INSERT INTO macro_indicators (indicator_code, indicator_name, value, released_at)
                            VALUES (:code, :name, :val, :ts)
                            ON CONFLICT DO NOTHING
                        """),
                        {"code": code, "name": name, "val": float(obs["value"]), "ts": released_at},
                    )
            except Exception as exc:
                logger.error("[fred] failed to fetch %s: %s", code, exc)

        await session.commit()
        logger.info("[fred] macro indicators updated.")


async def _fetch_series(series_id: str) -> dict:
    url = f"{BASE_URL}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 90,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()
