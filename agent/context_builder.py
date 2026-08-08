"""
Builds the structured context dict from DB queries for the agent.
Enforces a 2000-token budget by trimming lower-priority data first.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from aggregation.macro_overlay import compute_macro_score
from aggregation.scorer import compute_aggregate_scores, get_source_breakdown, get_top_events
from db.session import AsyncSessionLocal

import sqlalchemy as sa

logger = logging.getLogger(__name__)

MAX_CONTEXT_TOKENS = 2000


async def build_context(ticker: str) -> dict[str, Any]:
    """Assemble full context dict for the agent."""
    scores = await compute_aggregate_scores(ticker)

    async with AsyncSessionLocal() as session:
        company_row = await session.execute(
            sa.text("SELECT name, sector, industry FROM companies WHERE ticker = :t"),
            {"t": ticker},
        )
        company = company_row.fetchone()

    company_name = company.name if company else ticker
    sector = company.sector if company else None

    top_events = await get_top_events(ticker, days=7, limit=10)
    source_breakdown = await get_source_breakdown(ticker, days=7)
    macro = await compute_macro_score(sector)

    # Document count
    async with AsyncSessionLocal() as session:
        count_row = await session.execute(
            sa.text("""
                SELECT COUNT(*) FROM sentiment_scores s
                WHERE s.ticker = :t
                AND s.scored_at >= now() - INTERVAL '7 days'
            """),
            {"t": ticker},
        )
        doc_count = count_row.scalar() or 0

    # Viral alert: reddit volume anomaly (simple check)
    viral_alert = False
    async with AsyncSessionLocal() as session:
        viral_row = await session.execute(
            sa.text("""
                SELECT COUNT(*) FROM raw_documents d
                JOIN document_companies dc ON dc.document_id = d.id
                WHERE dc.ticker = :t
                AND d.source IN ('reddit_stocks', 'reddit_wsb')
                AND d.published_at >= now() - INTERVAL '4 hours'
            """),
            {"t": ticker},
        )
        recent_social = viral_row.scalar() or 0
        if recent_social > 15:
            viral_alert = True

    context = {
        "ticker": ticker,
        "company_name": company_name,
        "sector": sector or "Unknown",
        "sentiment_1d": scores.get("score_1d"),
        "sentiment_7d": scores.get("score_7d"),
        "sentiment_30d": scores.get("score_30d"),
        "trend": scores.get("trend"),
        "document_count_7d": doc_count,
        "top_events": top_events,
        "source_breakdown": source_breakdown,
        "viral_alert": viral_alert,
        "macro_overlay": macro,
    }

    return _enforce_token_budget(context)


def _enforce_token_budget(context: dict) -> dict:
    """Trim context until JSON representation is under MAX_CONTEXT_TOKENS tokens (approx)."""
    def _approx_tokens(obj: Any) -> int:
        return len(json.dumps(obj).split())

    # Trim social detail first
    if _approx_tokens(context) > MAX_CONTEXT_TOKENS:
        breakdown = context.get("source_breakdown", {})
        for social_key in ("tier_4", "tier_5"):
            if social_key in breakdown:
                breakdown[social_key] = {"count": breakdown[social_key].get("count"), "note": "detail trimmed"}

    # Trim events list
    if _approx_tokens(context) > MAX_CONTEXT_TOKENS:
        context["top_events"] = context["top_events"][:5]

    # Drop macro detail
    if _approx_tokens(context) > MAX_CONTEXT_TOKENS:
        macro = context.get("macro_overlay", {})
        context["macro_overlay"] = {"score": macro.get("score"), "description": macro.get("description")}

    return context
