"""
APScheduler-based ingestion daemon with fast and slow lane worker pools.
Fast lane: 2 asyncio workers draining CRITICAL tasks.
Slow lane: 4 asyncio workers draining STANDARD tasks.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from functools import partial
from typing import Callable

import click
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.review_agent import run_review
from config.settings import settings
from ingestion.sources.sec_edgar import SecEdgarSource
from ingestion.sources.company_ir import CompanyIRSource
from ingestion.sources.yahoo_finance import YahooFinanceSource
from ingestion.sources.finnhub import FinnhubNewsSource, FinnhubTranscriptSource
from ingestion.sources.reddit import build_reddit_sources
from ingestion.sources.stocktwits import StockTwitsSource
from ingestion.sources.fred import fetch_and_store_indicators
from ingestion.sources.federal_reserve import FederalReserveSource
from output.formatter import format_summary_text
from output.persistence import write_analysis_output
from processing.worker import process_next_task

logger = logging.getLogger(__name__)

MARKET_TIMEZONE = "America/New_York"

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


async def _send_email_summary(recipients: list[str], subject: str, body: str) -> None:
    if not settings.smtp_host or not recipients:
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_username or "stock-sentiment"
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            if settings.smtp_use_tls:
                server.starttls()

        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info("[scheduler/email] Sent %d summary email(s)", len(recipients))
    except Exception as exc:
        logger.error("[scheduler/email] Could not send summary email: %s", exc)


async def _run_analysis_cycle(output_callback: Callable[[str], None] | None = None, email_recipients: list[str] | None = None) -> list[dict]:
    tickers = await _get_watched_tickers()
    if not tickers:
        logger.info("[scheduler/analysis] No companies in watchlist; skipping analysis")
        return []

    results = []
    for ticker in tickers:
        try:
            result = await run_review(ticker)
            results.append(result)
            write_analysis_output(result)
            if output_callback:
                output_callback(format_summary_text(result))
            else:
                click.echo(format_summary_text(result))
        except Exception as exc:
            logger.error("[scheduler/analysis] %s analysis failed: %s", ticker, exc)

    if email_recipients:
        body = "\n\n".join(format_summary_text(result) for result in results)
        if body:
            await _send_email_summary(email_recipients, "Stock Sentiment Summary", body)

    return results


async def _run_ingestion_cycle(
    output_callback: Callable[[str], None] | None = None,
    email_recipients: list[str] | None = None,
    run_analysis: bool = True,
) -> None:
    await _run_fast_sources()
    await _run_slow_sources()
    if run_analysis:
        await _run_analysis_cycle(output_callback=output_callback, email_recipients=email_recipients)
    else:
        logger.info("[scheduler] Analysis disabled for this ingestion cycle")


async def _run_transcripts() -> None:
    tickers = await _get_watched_tickers()
    for ticker in tickers:
        try:
            await TRANSCRIPT_SOURCE.ingest(ticker)
        except Exception as exc:
            logger.error("[scheduler/transcripts] %s error: %s", ticker, exc)


async def _fast_lane_worker() -> None:
    consecutive_errors = 0
    while True:
        try:
            found = await process_next_task(priority_filter="CRITICAL")
            consecutive_errors = 0
            if not found:
                await asyncio.sleep(5)
        except Exception as exc:
            consecutive_errors += 1
            backoff = min(5 * 2 ** consecutive_errors, 300)  # cap at 5 min
            logger.error("[worker/fast] %s (retry in %ds)", exc, backoff)
            await asyncio.sleep(backoff)


async def _slow_lane_worker() -> None:
    consecutive_errors = 0
    while True:
        try:
            found = await process_next_task(priority_filter=None)
            consecutive_errors = 0
            if not found:
                await asyncio.sleep(15)
        except Exception as exc:
            consecutive_errors += 1
            backoff = min(15 * 2 ** consecutive_errors, 300)  # cap at 5 min
            logger.error("[worker/slow] %s (retry in %ds)", exc, backoff)
            await asyncio.sleep(backoff)


def build_scheduler(
    interval_minutes: int | None = None,
    output_callback: Callable[[str], None] | None = None,
    email_recipients: list[str] | None = None,
    run_analysis: bool = True,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    cadence_minutes = 15 if interval_minutes is None else interval_minutes
    scheduler.add_job(
        partial(
            _run_ingestion_cycle,
            output_callback=output_callback,
            email_recipients=email_recipients,
            run_analysis=run_analysis,
        ),
        IntervalTrigger(minutes=cadence_minutes),
        id="ingestion_cycle",
        max_instances=1,
    )
    logger.info("[scheduler] Started. Ingestion cycle every %s minutes.", cadence_minutes)

    # Earnings transcripts: daily at 6AM ET
    scheduler.add_job(_run_transcripts, CronTrigger(hour=6, minute=0, timezone=MARKET_TIMEZONE), id="transcripts")

    # FRED macro data: daily at 9AM ET
    scheduler.add_job(fetch_and_store_indicators, CronTrigger(hour=9, minute=0, timezone=MARKET_TIMEZONE), id="fred")

    return scheduler


async def run_daemon(
    interval_minutes: int | None = None,
    output_callback: Callable[[str], None] | None = None,
    email_recipients: list[str] | None = None,
    run_analysis: bool = True,
) -> None:
    """Start the ingestion daemon with fast and slow lane workers."""
    from processing.model_registry import load_models, format_startup_health_report
    report = load_models()
    if output_callback:
        for line in format_startup_health_report(report):
            output_callback(line)

    scheduler = build_scheduler(
        interval_minutes=interval_minutes,
        output_callback=output_callback,
        email_recipients=email_recipients,
        run_analysis=run_analysis,
    )
    scheduler.start()

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
    finally:
        scheduler.shutdown(wait=False)
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
