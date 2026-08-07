"""
Sentiment aggregation across time windows (1d, 7d, 30d).
Uses the sentiment_hourly continuous aggregate for efficiency.
Applies recency decay and macro overlay.
"""

from __future__ import annotations

import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import sqlalchemy as sa

from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

DECAY_LAMBDAS = {
    "1d": 0.70,
    "7d": 0.14,
    "30d": 0.035,
}

WINDOW_DAYS = {"1d": 1, "7d": 7, "30d": 30}


async def compute_aggregate_scores(ticker: str) -> dict[str, float | None]:
    """
    Compute weighted sentiment scores for 1d, 7d, 30d windows.
    Returns dict with keys 'score_1d', 'score_7d', 'score_30d', 'trend'.
    """
    results = {}
    async with AsyncSessionLocal() as session:
        for window_key, days in WINDOW_DAYS.items():
            score = await _compute_window(ticker, days, DECAY_LAMBDAS[window_key], session)
            results[f"score_{window_key}"] = score

    # Trend: compare 7d score vs prior 7d
    results["trend"] = _compute_trend(results.get("score_7d"), results.get("score_30d"))
    return results


async def _compute_window(
    ticker: str, days: int, lam: float, session
) -> Optional[float]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    # Query raw sentiment_scores for this window (continuous aggregate covers last 30 days)
    rows = await session.execute(
        sa.text("""
            SELECT raw_score, source_weight, confidence_mult, engagement_mult, scored_at
            FROM sentiment_scores
            WHERE ticker = :ticker AND scored_at >= :cutoff
            ORDER BY scored_at DESC
        """),
        {"ticker": ticker, "cutoff": cutoff},
    )
    records = rows.fetchall()
    if not records:
        return None

    now = datetime.now(tz=timezone.utc)
    numerator = 0.0
    denominator = 0.0

    for row in records:
        age_days = (now - row.scored_at.replace(tzinfo=timezone.utc)).total_seconds() / 86400
        recency_w = math.exp(-lam * age_days)
        total_w = row.source_weight * row.confidence_mult * row.engagement_mult * recency_w
        numerator += row.raw_score * total_w
        denominator += total_w

    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _compute_trend(score_7d: Optional[float], score_30d: Optional[float]) -> str:
    if score_7d is None or score_30d is None:
        return "unknown"
    diff = score_7d - score_30d
    if diff > 0.05:
        return "improving"
    if diff < -0.05:
        return "deteriorating"
    return "stable"


async def get_source_breakdown(ticker: str, days: int = 7) -> dict:
    """Return average sentiment score per source tier group."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            sa.text("""
                SELECT source_tier, AVG(raw_score) as avg_score, COUNT(*) as doc_count
                FROM sentiment_scores
                WHERE ticker = :ticker AND scored_at >= :cutoff
                GROUP BY source_tier
                ORDER BY source_tier
            """),
            {"ticker": ticker, "cutoff": cutoff},
        )
        breakdown = {}
        for row in rows.fetchall():
            tier_label = {1: "tier_1", 2: "tier_2", 3: "tier_3", 4: "tier_4", 5: "tier_5"}.get(row.source_tier, f"tier_{row.source_tier}")
            breakdown[tier_label] = {
                "score": round(float(row.avg_score), 4),
                "count": row.doc_count,
            }
        return breakdown


async def get_top_events(ticker: str, days: int = 7, limit: int = 10) -> list[dict]:
    """Return top events for a ticker ordered by importance and recency."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            sa.text("""
                SELECT DISTINCT ON (e.event_id)
                    e.event_id, e.event_type, e.headline, e.importance, e.created_at,
                    s.raw_score
                FROM events e
                JOIN event_documents ed ON ed.event_id = e.event_id
                JOIN raw_documents d ON d.id = ed.document_id
                JOIN document_companies dc ON dc.document_id = d.id
                LEFT JOIN sentiment_scores s ON s.document_id = d.id AND s.ticker = :ticker
                WHERE dc.ticker = :ticker AND e.created_at >= :cutoff
                ORDER BY e.event_id,
                    CASE e.importance WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END,
                    e.created_at DESC
                LIMIT :limit
            """),
            {"ticker": ticker, "cutoff": cutoff, "limit": limit},
        )
        events = []
        for row in rows.fetchall():
            events.append({
                "event_id": row.event_id,
                "type": row.event_type,
                "headline": row.headline,
                "importance": row.importance,
                "date": row.created_at.strftime("%Y-%m-%d") if row.created_at else "",
                "score": round(float(row.raw_score), 3) if row.raw_score else None,
            })
        return events
