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
import json
import logging
import os
import re
import sys

import click

# Ensure project root is on path when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _configure_logging(log_file: str | None = None) -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file)
        except OSError as exc:
            raise click.ClickException(f"Could not open log file '{log_file}': {exc}") from exc
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(logging.INFO)


def parse_interval_to_minutes(interval: str) -> int:
    """Parse human-readable intervals such as 15m, 1h, daily, weekly, or 2 weeks."""
    normalized = re.sub(r"\s+", " ", interval.strip().lower()).replace("_", " ")

    if not normalized:
        raise ValueError("interval cannot be empty")

    special = {
        "hourly": 60,
        "1h": 60,
        "1hr": 60,
        "1hour": 60,
        "daily": 24 * 60,
        "1d": 24 * 60,
        "1day": 24 * 60,
        "weekly": 7 * 24 * 60,
        "1w": 7 * 24 * 60,
        "1week": 7 * 24 * 60,
        "biweekly": 14 * 24 * 60,
        "fortnightly": 14 * 24 * 60,
        "2w": 14 * 24 * 60,
        "2weeks": 14 * 24 * 60,
        "2 weeks": 14 * 24 * 60,
    }
    if normalized in special:
        return special[normalized]

    if normalized.startswith("every "):
        normalized = normalized[len("every "):].strip()

    match = re.fullmatch(r"(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)", normalized)
    if not match:
        raise ValueError(
            "interval must be a number plus a unit (e.g. 15m, 1h, 1d, 2w) or a named interval (hourly, daily, weekly, biweekly)"
        )

    value = int(match.group(1))
    unit = match.group(2)
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return value
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return value * 60
    if unit in {"d", "day", "days"}:
        return value * 24 * 60
    if unit in {"w", "week", "weeks"}:
        return value * 7 * 24 * 60

    raise ValueError(f"unsupported interval unit '{unit}'")


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
        stderr = result.stderr.strip() or result.stdout.strip() or "No Alembic output was produced."
        raise click.ClickException(f"[db-init] Migration failed:\n{stderr}")
    if result.stdout:
        click.echo(result.stdout)

    click.echo("[db-init] Setting up TimescaleDB hypertables...")
    from db.timescale_setup import run_timescale_setup
    await run_timescale_setup(settings.db_url)

    click.echo("[db-init] Seeding source tiers...")
    await _seed_source_tiers()

    click.echo("[db-init] Done.")

async def _ensure_db_ready() -> None:
    """Raise ClickException with a clear message if migrations have not been run."""
    import sqlalchemy as sa
    from db.session import AsyncSessionLocal

    required_tables = ["companies", "task_queue", "raw_documents"]
    try:
        async with AsyncSessionLocal() as session:
            for table in required_tables:
                await session.execute(
                    sa.text(f"SELECT 1 FROM {table} LIMIT 0")
                )
    except Exception:
        raise click.ClickException(
            "Database is not initialised — required tables are missing.\n"
            "Run 'python cli.py db-init' first, then retry."
        )

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


@cli.command("inspect")
@click.argument("company")
@click.option("--limit", type=int, default=10, show_default=True, help="Maximum number of ingested documents to return")
@click.option("--text", "as_text", is_flag=True, help="Render the retrieved documents as a human-readable report")
def inspect_company(company: str, limit: int, as_text: bool):
    """Inspect ingested documents for a company from the local database."""
    asyncio.run(_inspect_company_command(company, limit=limit, as_text=as_text))


async def _inspect_company_command(name_or_ticker: str, *, limit: int = 10, as_text: bool = False):
    try:
        documents = await _inspect_company(name_or_ticker, limit=limit)
    except click.ClickException:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard for runtime DB issues
        raise click.ClickException(f"Could not inspect documents for '{name_or_ticker}': {exc}") from exc

    if as_text:
        if not documents:
            click.echo(f"No ingested documents found for '{name_or_ticker}'.")
            return
        click.echo(f"Ingested documents for {documents[0]['ticker']}:")
        for document in documents:
            title = document.get("title") or "(no title)"
            source = document.get("source") or "unknown"
            click.echo(f"- [{source}] {title}")
            if document.get("body"):
                click.echo(f"  {document['body']}")
            if document.get("raw_json"):
                raw_json = json.dumps(document["raw_json"], indent=2, sort_keys=True, default=str)
                click.echo(f"  raw_json: {raw_json}")
        return

    click.echo(json.dumps(documents, indent=2, sort_keys=True, default=str))


async def _inspect_company(name_or_ticker: str, limit: int = 10) -> list[dict]:
    from db.session import AsyncSessionLocal
    from resolution.ticker_resolver import resolve_interactive
    import sqlalchemy as sa

    async with AsyncSessionLocal() as session:
        ticker = await resolve_interactive(name_or_ticker, session)
        if not ticker:
            raise click.ClickException(
                f"Could not resolve '{name_or_ticker}'. Use 'python cli.py add <company>' first."
            )

        rows = await session.execute(
            sa.text(
                """
                SELECT
                    rd.id,
                    dc.ticker,
                    rd.source,
                    rd.source_subtype,
                    rd.title,
                    rd.body,
                    rd.published_at,
                    rd.retrieved_at,
                    rd.raw_json
                FROM raw_documents rd
                JOIN document_companies dc ON dc.document_id = rd.id
                WHERE dc.ticker = :ticker
                ORDER BY rd.id DESC
                LIMIT :limit
                """
            ),
            {"ticker": ticker, "limit": max(limit, 1)},
        )

        documents = []
        for row in rows:
            documents.append({
                "id": row.id,
                "ticker": row.ticker,
                "source": row.source,
                "source_subtype": row.source_subtype,
                "title": row.title,
                "body": row.body,
                "published_at": row.published_at.isoformat() if row.published_at else None,
                "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
                "raw_json": row.raw_json,
            })

    return documents


@cli.command("analyze")
@click.argument("company")
@click.option("--fresh", is_flag=True, help="Force fresh analysis (bypass 6-hour cache)")
def analyze(company: str, fresh: bool):
    """Run sentiment analysis for a company and display the investment summary."""
    asyncio.run(_analyze(company, fresh))


async def _analyze(name_or_ticker: str, force_refresh: bool):
    from db.session import AsyncSessionLocal
    from resolution.ticker_resolver import resolve_interactive
    from output.formatter import render_summary
    from output.persistence import write_analysis_output

    try:
        from agent.review_agent import run_review
    except ModuleNotFoundError as exc:
        if exc.name == "openai":
            raise click.ClickException(
                "Missing dependency 'openai'. Install project dependencies with "
                "'pip install -r requirements.txt' and retry."
            ) from exc
        raise

    async with AsyncSessionLocal() as session:
        ticker = await resolve_interactive(name_or_ticker, session)
        if not ticker:
            click.echo(f"[analyze] Could not resolve '{name_or_ticker}'. Use 'python cli.py add <company>' first.")
            return

    click.echo(f"[analyze] Running analysis for {ticker}...")
    try:
        result = await run_review(ticker, force_refresh=force_refresh)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    output_paths = write_analysis_output(result)
    click.echo(f"[analyze] Saved analysis output to {output_paths[0].parent}")
    render_summary(result)


@cli.command("run")
@click.option("--once", is_flag=True, help="Run one ingestion cycle then exit (for testing)")
@click.option(
    "--interval",
    type=str,
    default=None,
    help="How often the daemon should run the ingestion cycle (examples: 15m, 1h, daily, weekly, 2 weeks)",
)
@click.option(
    "--email-to",
    "email_tos",
    multiple=True,
    help="Email address to receive the generated summary report. May be supplied multiple times.",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, writable=True, path_type=str),
    help="Write logs to a file in addition to stderr",
)
@click.option(
    "--analysis/--no-analysis",
    "run_analysis",
    default=True,
    show_default=True,
    help="Run company analysis during each ingestion cycle.",
)
def run_daemon(once: bool, interval: str | None, email_tos: tuple[str, ...], log_file: str | None, run_analysis: bool):
    """Start the ingestion and processing daemon."""
    from config.settings import settings

    _configure_logging(log_file)
    interval_minutes = None
    if interval:
        try:
            interval_minutes = parse_interval_to_minutes(interval)
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--interval") from exc

    configured_recipients = [recipient.strip() for recipient in email_tos if recipient.strip()]
    if not configured_recipients and settings.email_to:
        configured_recipients = [recipient.strip() for recipient in settings.email_to.split(",") if recipient.strip()]

    if once:
        asyncio.run(_run_once(email_tos=tuple(configured_recipients), run_analysis=run_analysis))
    else:
        asyncio.run(_run_daemon(interval_minutes=interval_minutes, email_tos=tuple(configured_recipients), run_analysis=run_analysis))


async def _run_once(email_tos: tuple[str, ...] = (), run_analysis: bool = True):
    from ingestion.scheduler import _run_ingestion_cycle
    from processing.model_registry import load_models
    await _ensure_db_ready()
    click.echo("[run] Loading models...")
    load_models()
    click.echo("[run] Running one ingestion cycle...")
    await _run_ingestion_cycle(output_callback=click.echo, email_recipients=list(email_tos), run_analysis=run_analysis)
    click.echo("[run] Done.")


async def _run_daemon(interval_minutes: int | None = None, email_tos: tuple[str, ...] = (), run_analysis: bool = True):
    from ingestion.scheduler import run_daemon
    await _ensure_db_ready()
    if interval_minutes is None:
        click.echo("[run] Starting ingestion daemon. Press Ctrl+C to stop.")
    else:
        click.echo(f"[run] Starting ingestion daemon with a {interval_minutes}-minute interval. Press Ctrl+C to stop.")
    await run_daemon(
        interval_minutes=interval_minutes,
        output_callback=click.echo,
        email_recipients=list(email_tos),
        run_analysis=run_analysis,
    )


if __name__ == "__main__":
    cli()
