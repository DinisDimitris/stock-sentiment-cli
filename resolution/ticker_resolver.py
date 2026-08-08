"""
Five-step ticker resolution waterfall. Short-circuits at first successful match.
Steps: exact ticker → alias table → trigram fuzzy → SEC EDGAR search → Finnhub search.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx
from rapidfuzz import fuzz
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models import Company, TickerAlias


async def resolve(name_or_ticker: str, session: AsyncSession) -> Optional[str]:
    """Return canonical ticker string or None if unresolvable."""
    needle = name_or_ticker.strip()

    ticker = await _step1_exact(needle, session)
    if ticker:
        return ticker

    ticker = await _step2_alias(needle, session)
    if ticker:
        return ticker

    ticker = await _step3_trigram(needle, session)
    if ticker:
        return ticker

    ticker = await _step4_sec_edgar(needle)
    if ticker:
        await _add_alias(needle, ticker, "sec_edgar", session)
        return ticker

    ticker = await _step5_finnhub(needle)
    if ticker:
        await _add_alias(needle, ticker, "finnhub", session)
        return ticker

    return None


async def resolve_interactive(name_or_ticker: str, session: AsyncSession) -> Optional[str]:
    """Like resolve() but prompts user to confirm ambiguous trigram matches."""
    needle = name_or_ticker.strip()

    ticker = await _step1_exact(needle, session)
    if ticker:
        return ticker

    ticker = await _step2_alias(needle, session)
    if ticker:
        return ticker

    ticker, confirmed = await _step3_trigram_interactive(needle, session)
    if ticker:
        if confirmed:
            await _add_alias(needle, ticker, "user_resolved", session)
            await session.commit()
        return ticker

    ticker = await _step4_sec_edgar(needle)
    if ticker:
        await _add_alias(needle, ticker, "sec_edgar", session)
        await session.commit()
        return ticker

    ticker = await _step5_finnhub(needle)
    if ticker:
        await _add_alias(needle, ticker, "finnhub", session)
        await session.commit()
        return ticker

    return None


async def _step1_exact(needle: str, session: AsyncSession) -> Optional[str]:
    row = await session.execute(
        select(Company.ticker).where(Company.ticker == needle.upper())
    )
    return row.scalar_one_or_none()


async def _step2_alias(needle: str, session: AsyncSession) -> Optional[str]:
    row = await session.execute(
        select(TickerAlias.ticker).where(
            text("LOWER(alias) = LOWER(:needle)")
        ).params(needle=needle)
    )
    return row.scalar_one_or_none()


async def _step3_trigram(needle: str, session: AsyncSession) -> Optional[str]:
    ticker, _ = await _trigram_lookup(needle, session)
    return ticker


async def _step3_trigram_interactive(
    needle: str, session: AsyncSession
) -> tuple[Optional[str], bool]:
    rows = await session.execute(
        select(Company.ticker, Company.name)
    )
    companies = rows.fetchall()
    if not companies:
        return None, False

    best = max(companies, key=lambda r: fuzz.token_sort_ratio(needle.lower(), r.name.lower()))
    score = fuzz.token_sort_ratio(needle.lower(), best.name.lower())

    if score >= 75:
        return best.ticker, False  # auto-accept, no need to save as user_resolved

    if score >= 40:
        answer = input(f"Did you mean {best.ticker} ({best.name})? [y/N] ").strip().lower()
        if answer == "y":
            return best.ticker, True

    return None, False


async def _trigram_lookup(needle: str, session: AsyncSession) -> tuple[Optional[str], float]:
    rows = await session.execute(select(Company.ticker, Company.name))
    companies = rows.fetchall()
    if not companies:
        return None, 0.0

    best = max(companies, key=lambda r: fuzz.token_sort_ratio(needle.lower(), r.name.lower()))
    score = fuzz.token_sort_ratio(needle.lower(), best.name.lower())
    if score >= 75:
        return best.ticker, score
    return None, score


async def _step4_sec_edgar(needle: str) -> Optional[str]:
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {"q": needle, "forms": "10-K", "dateRange": "custom", "startdt": "2020-01-01"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params, headers={"User-Agent": "StockSentimentBot admin@example.com"})
            r.raise_for_status()
            data = r.json()
            hits = data.get("hits", {}).get("hits", [])
            if hits:
                # Extract ticker from entity name — EDGAR returns entity_name and file_num
                entity = hits[0].get("_source", {})
                ticker = entity.get("ticker", "")
                if ticker:
                    return ticker.upper()
    except Exception:
        pass
    return None


async def _step5_finnhub(needle: str) -> Optional[str]:
    if not settings.finnhub_key:
        return None
    url = "https://finnhub.io/api/v1/search"
    params = {"q": needle, "token": settings.finnhub_key}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            results = data.get("result", [])
            for item in results:
                if item.get("type") == "Common Stock":
                    return item["symbol"].upper()
    except Exception:
        pass
    return None


async def _add_alias(
    alias: str, ticker: str, alias_type: str, session: AsyncSession
) -> None:
    company_exists = await session.execute(
        select(Company.ticker).where(Company.ticker == ticker)
    )
    if not company_exists.scalar_one_or_none():
        return

    existing = await session.execute(
        select(TickerAlias).where(
            TickerAlias.alias == alias.lower(),
            TickerAlias.ticker == ticker,
        )
    )
    if not existing.scalar_one_or_none():
        session.add(TickerAlias(
            alias=alias.lower(),
            ticker=ticker,
            alias_type=alias_type,
            confidence=1.0,
        ))
