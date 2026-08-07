"""Minimal FastAPI wrapper around the CLI analyze command."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.review_agent import run_review
from db.session import AsyncSessionLocal
from resolution.ticker_resolver import resolve

app = FastAPI(title="Stock Sentiment API")


class AnalyzeRequest(BaseModel):
    company: str
    force_refresh: bool = False


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    async with AsyncSessionLocal() as session:
        ticker = await resolve(req.company, session)
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Could not resolve '{req.company}' to a ticker.")
    result = await run_review(ticker, force_refresh=req.force_refresh)
    return result


@app.get("/status/{ticker}")
async def status(ticker: str):
    import sqlalchemy as sa
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        row = await session.execute(
            sa.text("""
                SELECT ticker, name, sector, backfill_status, added_at
                FROM companies WHERE ticker = :t
            """),
            {"t": ticker.upper()},
        )
        company = row.fetchone()
        if not company:
            raise HTTPException(status_code=404, detail=f"{ticker} not in watchlist.")
        return {
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "backfill_status": company.backfill_status,
            "added_at": str(company.added_at),
        }
