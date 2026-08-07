#!/usr/bin/env python3
"""
Stock Sentiment CLI

Commands:
  db-init           Set up TimescaleDB extensions, hypertables, and seed data
  add <company>     Add a company to the watchlist (resolves ticker automatically)
  remove <ticker>   Remove a company from the watchlist
  run               Start the ingestion and processing daemon
  analyze <company> Run sentiment analysis for a company
  list              Show all watched companies
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import click

# Ensure project root is on path when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


@click.group()
def cli():
    pass


@cli.command("db-init")
def db_init():
    """Initialise the database: run Alembic migrations + TimescaleDB setup."""
    asyncio.run(_db_init())


async def _db_init():
    import subprocess
    from config.settings import settings

    click.echo("[db-init] Running Alembic migrations...")
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if result.returncode != 0:
        click.echo(f"[db-init] Migration error:\n{result.stderr}")
        return
    click.echo(result.stdout)

    click.echo("[db-init] Setting up TimescaleDB hypertables...")
    from db.timescale_setup import run_timescale_setup
    await run_timescale_setup(settings.db_url)

    click.echo("[db-init] Seeding source tiers...")
    await _seed_source_tiers()

    click.echo("[db-init] Done.")


async def _seed_source_tiers():
    import yaml
    from pathlib import Path
    import sqlalchemy as sa
    from db.session import AsyncSessionLocal

    config_path = Path(__file__).parent / "config" / "source_tiers.yaml"
    config = yaml.safe_load(config_path.read_text())

    async with AsyncSessionLocal() as session:
        for tier_def in config.get("tiers", []):
            await session.execute(
                sa.text("""
                    INSERT INTO source_tiers (source_name, tier, base_weight, description)
                    VALUES (:name, :tier, :weight, :desc)
                    ON CONFLICT (source_name) DO UPDATE
                    SET tier = :tier, base_weight = :weight, description = :desc
                """),
                {
                    "name": tier_def["source_name"],
                    "tier": tier_def["tier"],
                    "weight": tier_def["base_weight"],
                    "desc": tier_def.get("description", ""),
                },
            )
        await session.commit()
    click.echo("[db-init] Source tiers seeded.")


@cli.command("add")
@click.argument("company")
def add_company(company: str):
    """Add a company to the watchlist. Accepts company name or ticker."""
    asyncio.run(_add_company(company))


async def _add_company(name_or_ticker: str):
    from db.session import AsyncSessionLocal
    from resolution.ticker_resolver import resolve_interactive
    import sqlalchemy as sa

    async with AsyncSessionLocal() as session:
        ticker = await resolve_interactive(name_or_ticker, session)
        if not ticker:
            click.echo(f"[add] Could not resolve '{name_or_ticker}' to a ticker. Try using the exact ticker symbol.")
            return

        # Check if already exists
        existing = await session.execute(
            sa.text("SELECT ticker FROM companies WHERE ticker = :t"),
            {"t": ticker},
        )
        if existing.scalar_one_or_none():
            click.echo(f"[add] {ticker} is already in your watchlist.")
            return

        # Fetch company metadata from Finnhub
        name, sector, industry = await _fetch_company_metadata(ticker)

        from db.models import Company
        session.add(Company(
            ticker=ticker,
            name=name,
            sector=sector,
            industry=industry,
            backfill_status="pending",
        ))

        # Queue backfill
        from db.models import TaskQueue
        session.add(TaskQueue(
            task_type="backfill",
            priority="STANDARD",
            payload={"ticker": ticker, "days": 90},
        ))

        await session.commit()
        click.echo(f"[add] Added {ticker} ({name}) — sector: {sector or 'unknown'}.")
        click.echo(f"[add] Backfill queued (90 days SEC, 30 days news, 7 days social).")
        click.echo(f"[add] Run 'python cli.py run' to start ingestion.")


async def _fetch_company_metadata(ticker: str) -> tuple[str, str | None, str | None]:
    from config.settings import settings
    import httpx

    if settings.finnhub_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://finnhub.io/api/v1/stock/profile2",
                    params={"symbol": ticker, "token": settings.finnhub_key},
                )
                r.raise_for_status()
                d = r.json()
                return (
                    d.get("name", ticker),
                    d.get("finnhubIndustry"),
                    d.get("finnhubIndustry"),
                )
        except Exception:
            pass
    return ticker, None, None


@cli.command("remove")
@click.argument("ticker")
def remove_company(ticker: str):
    """Remove a company from the watchlist."""
    asyncio.run(_remove_company(ticker.upper()))


async def _remove_company(ticker: str):
    import sqlalchemy as sa
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sa.text("DELETE FROM companies WHERE ticker = :t RETURNING ticker"),
            {"t": ticker},
        )
        deleted = result.fetchone()
        await session.commit()
        if deleted:
            click.echo(f"[remove] {ticker} removed from watchlist.")
        else:
            click.echo(f"[remove] {ticker} not found in watchlist.")


@cli.command("list")
def list_companies():
    """List all companies in the watchlist."""
    asyncio.run(_list_companies())


async def _list_companies():
    import sqlalchemy as sa
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            sa.text("SELECT ticker, name, sector, backfill_status FROM companies ORDER BY ticker")
        )
        companies = rows.fetchall()
        if not companies:
            click.echo("No companies in watchlist. Run 'python cli.py add <company>'.")
            return
        click.echo(f"\n{'Ticker':<8} {'Name':<30} {'Sector':<25} {'Backfill'}")
        click.echo("-" * 75)
        for c in companies:
            click.echo(f"{c.ticker:<8} {(c.name or '')[:29]:<30} {(c.sector or 'unknown')[:24]:<25} {c.backfill_status}")


@cli.command("analyze")
@click.argument("company")
@click.option("--fresh", is_flag=True, help="Force fresh analysis (bypass 6-hour cache)")
def analyze(company: str, fresh: bool):
    """Run sentiment analysis for a company and display the investment summary."""
    asyncio.run(_analyze(company, fresh))


async def _analyze(name_or_ticker: str, force_refresh: bool):
    from db.session import AsyncSessionLocal
    from resolution.ticker_resolver import resolve_interactive
    from agent.review_agent import run_review
    from output.formatter import render_summary

    async with AsyncSessionLocal() as session:
        ticker = await resolve_interactive(name_or_ticker, session)
        if not ticker:
            click.echo(f"[analyze] Could not resolve '{name_or_ticker}'. Use 'python cli.py add <company>' first.")
            return

    click.echo(f"[analyze] Running analysis for {ticker}...")
    result = await run_review(ticker, force_refresh=force_refresh)
    render_summary(result)


@cli.command("run")
@click.option("--once", is_flag=True, help="Run one ingestion cycle then exit (for testing)")
def run_daemon(once: bool):
    """Start the ingestion and processing daemon."""
    if once:
        asyncio.run(_run_once())
    else:
        asyncio.run(_run_daemon())


async def _run_once():
    from ingestion.scheduler import _run_fast_sources, _run_slow_sources
    from processing.model_registry import load_models

    click.echo("[run] Loading models...")
    load_models()
    click.echo("[run] Running one ingestion cycle...")
    await _run_fast_sources()
    await _run_slow_sources()
    click.echo("[run] Done.")


async def _run_daemon():
    from ingestion.scheduler import run_daemon
    click.echo("[run] Starting ingestion daemon. Press Ctrl+C to stop.")
    await run_daemon()


if __name__ == "__main__":
    cli()
