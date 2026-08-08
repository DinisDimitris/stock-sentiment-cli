"""
Seed ticker_aliases with S&P 500 company common names from SEC EDGAR.
Run once: python -m resolution.seed_aliases
"""

from __future__ import annotations

import asyncio

import httpx

from db.session import AsyncSessionLocal
from db.models import Company, TickerAlias
from sqlalchemy import select


SP500_URL = "https://efts.sec.gov/LATEST/search-index?q=%22%22&forms=10-K&dateRange=custom&startdt=2024-01-01"

# Curated alias map for the most commonly queried large-caps.
# Format: common_name_lower → canonical_ticker
MANUAL_ALIASES: dict[str, str] = {
    "apple": "AAPL",
    "apple inc": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "meta": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "berkshire": "BRK.B",
    "berkshire hathaway": "BRK.B",
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "johnson & johnson": "JNJ",
    "johnson and johnson": "JNJ",
    "visa": "V",
    "mastercard": "MA",
    "procter gamble": "PG",
    "procter & gamble": "PG",
    "unitedhealth": "UNH",
    "exxon": "XOM",
    "exxonmobil": "XOM",
    "chevron": "CVX",
    "home depot": "HD",
    "abbvie": "ABBV",
    "merck": "MRK",
    "coca-cola": "KO",
    "coca cola": "KO",
    "pepsico": "PEP",
    "pepsi": "PEP",
    "broadcom": "AVGO",
    "costco": "COST",
    "walmart": "WMT",
    "eli lilly": "LLY",
    "amd": "AMD",
    "advanced micro devices": "AMD",
    "intel": "INTC",
    "qualcomm": "QCOM",
    "salesforce": "CRM",
    "adobe": "ADBE",
    "netflix": "NFLX",
    "paypal": "PYPL",
    "airbnb": "ABNB",
    "uber": "UBER",
    "lyft": "LYFT",
    "spotify": "SPOT",
    "snap": "SNAP",
    "twitter": "TWTR",
    "palantir": "PLTR",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    "rivian": "RIVN",
    "lucid": "LCID",
    "boeing": "BA",
    "lockheed": "LMT",
    "raytheon": "RTX",
    "caterpillar": "CAT",
    "deere": "DE",
    "john deere": "DE",
    "3m": "MMM",
    "at&t": "T",
    "verizon": "VZ",
    "comcast": "CMCSA",
    "disney": "DIS",
    "warner bros": "WBD",
    "paramount": "PARA",
    "fox": "FOX",
    "bank of america": "BAC",
    "wells fargo": "WFC",
    "citigroup": "C",
    "citi": "C",
    "goldman sachs": "GS",
    "goldman": "GS",
    "morgan stanley": "MS",
    "blackrock": "BLK",
    "charles schwab": "SCHW",
    "american express": "AXP",
    "amex": "AXP",
}


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        for alias, ticker in MANUAL_ALIASES.items():
            # Only add alias if the company exists in our DB
            company = await session.get(Company, ticker)
            if company is None:
                continue
            existing = await session.execute(
                select(TickerAlias).where(
                    TickerAlias.alias == alias,
                    TickerAlias.ticker == ticker,
                )
            )
            if not existing.scalar_one_or_none():
                session.add(TickerAlias(
                    alias=alias,
                    ticker=ticker,
                    alias_type="common_name",
                    confidence=1.0,
                ))
        await session.commit()
        print(f"[seed_aliases] Seeded {len(MANUAL_ALIASES)} aliases.")


if __name__ == "__main__":
    asyncio.run(seed())
