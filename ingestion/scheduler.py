"""
APScheduler-based ingestion daemon with fast and slow lane worker pools.
Fast lane: 2 asyncio workers draining CRITICAL tasks.
Slow lane: 4 asyncio workers draining STANDARD tasks.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ingestion.sources.sec_edgar import SecEdgarSource
from ingestion.sources.company_ir import CompanyIRSource
from ingestion.sources.yahoo_finance import YahooFinanceSource
from ingestion.sources.finnhub import FinnhubNewsSource, FinnhubTranscriptSource
from ingestion.sources.reddit import build_reddit_sources
from ingestion.sources.stocktwits import StockTwitsSource
from ingestion.sources.fred import fetch_and_store_indicators
from ingestion.sources.federal_reserve import FederalReserveSource
from processing.worker import process_next_task

logger = logging.getLogger(__name__)

SLOW_SOURCES = [
    CompanyIRSource(),
    YahooFinanceSource(),
    FinnhubNewsSource(),
    StockTwitsSource(),
    FederalReserveSource(),
]

FAST_SOURCES = [
    SecEdgarSource(),
]

TRANSCRIPT_SOURCE = FinnhubTranscriptSource()
REDDIT_SOURCES = build_reddit_sources()


async def _get_watched_tickers() -> list[str]:
    from db.session import AsyncSessionLocal
    import sqlalchemy as sa
    async with AsyncSessionLocal() as session:
        rows = await session.execute(sa.text("SELECT ticker FROM companies ORDER BY ticker"))
        return [r.ticker for r in rows.fetchall()]


async def _run_fast_sources() -> None:
    tickers = await _get_watched_tickers()
    if not tickers:
        return
    for ticker in tickers:
        for source in FAST_SOURCES:
            try:
                count = await source.ingest(ticker)
                if count > 0:
                    logger.info("[scheduler/fast] %s: %d new docs from %s", ticker, count, source.source_name)
            except Exception as exc:
                logger.error("[scheduler/fast] %s/%s error: %s", source.source_name, ticker, exc)


async def _run_slow_sources() -> None:
    tickers = await _get_watched_tickers()
    if not tickers:
        return
    for ticker in tickers:
        for source in SLOW_SOURCES:
            try:
                count = await source.ingest(ticker)
                if count > 0:
                    logger.info("[scheduler/slow] %s: %d new docs from %s", ticker, count, source.source_name)
            except Exception as exc:
                logger.error("[scheduler/slow] %s/%s error: %s", source.source_name, ticker, exc)


async def _run_reddit() -> None:
    tickers = await _get_watched_tickers()
    for ticker in tickers:
        for source in REDDIT_SOURCES:
            try:
                await source.ingest(ticker)
            except Exception as exc:
                logger.error("[scheduler/reddit] %s error: %s", ticker, exc)


async def _run_transcripts() -> None:
    tickers = await _get_watched_tickers()
    for ticker in tickers:
        try:
            await TRANSCRIPT_SOURCE.ingest(ticker)
        except Exception as exc:
            logger.error("[scheduler/transcripts] %s error: %s", ticker, exc)


async def _fast_lane_worker() -> None:
    """Continuously drain CRITICAL tasks."""
    while True:
        try:
            found = await process_next_task(priority_filter="CRITICAL")
            if not found:
                await asyncio.sleep(5)
        except Exception as exc:
            logger.error("[worker/fast] %s", exc)
            await asyncio.sleep(5)


async def _slow_lane_worker() -> None:
    """Continuously drain STANDARD tasks."""
    while True:
        try:
            found = await process_next_task(priority_filter=None)
            if not found:
                await asyncio.sleep(15)
        except Exception as exc:
            logger.error("[worker/slow] %s", exc)
            await asyncio.sleep(15)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Fast lane: SEC EDGAR 8-K every 15 minutes
    scheduler.add_job(_run_fast_sources, IntervalTrigger(minutes=15), id="fast_sources", max_instances=1)

    # Slow lane: general news/IR every 30 minutes
    scheduler.add_job(_run_slow_sources, IntervalTrigger(minutes=30), id="slow_sources", max_instances=1)

    # Reddit: every hour for r/stocks/investing, every 30min for WSB
    #scheduler.add_job(_run_reddit, IntervalTrigger(minutes=60), id="reddit", max_instances=1)

    # Earnings transcripts: daily at 6AM ET
    scheduler.add_job(_run_transcripts, CronTrigger(hour=6, minute=0, timezone="US/Eastern"), id="transcripts")

    # FRED macro data: daily at 9AM ET
    scheduler.add_job(fetch_and_store_indicators, CronTrigger(hour=9, minute=0, timezone="US/Eastern"), id="fred")

    return scheduler


async def run_daemon() -> None:
    """Start the ingestion daemon with fast and slow lane workers."""
    from processing.model_registry import load_models
    load_models()

    scheduler = build_scheduler()
    scheduler.start()
    logger.info("[scheduler] Started. Fast lane: 15min. Slow lane: 30min.")

    # Start worker pools
    workers = [
        asyncio.create_task(_fast_lane_worker(), name="fast_worker_1"),
        asyncio.create_task(_fast_lane_worker(), name="fast_worker_2"),
        asyncio.create_task(_slow_lane_worker(), name="slow_worker_1"),
        asyncio.create_task(_slow_lane_worker(), name="slow_worker_2"),
        asyncio.create_task(_slow_lane_worker(), name="slow_worker_3"),
        asyncio.create_task(_slow_lane_worker(), name="slow_worker_4"),
    ]

    try:
        await asyncio.gather(*workers)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("[scheduler] Shutting down...")
        scheduler.shutdown()
        for w in workers:
            w.cancel()
