"""
Sentiment document worker. Dequeues tasks from task_queue and scores documents.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RawDocument, TaskQueue
from db.session import AsyncSessionLocal
from processing.router import route_model, score_text

logger = logging.getLogger(__name__)

_SOCIAL_SOURCES = {"reddit_stocks", "reddit_wsb", "stocktwits"}


async def process_next_task(priority_filter: str | None = None) -> bool:
    """Claim and process one task. Returns True if a task was processed."""
    async with AsyncSessionLocal() as session:
        # Claim one task atomically using SKIP LOCKED
        query = """
            UPDATE task_queue SET status = 'claimed', claimed_at = now(), attempts = attempts + 1
            WHERE task_id = (
                SELECT task_id FROM task_queue
                WHERE status = 'pending'
                {priority_clause}
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING task_id, task_type, payload, priority
        """.format(
            priority_clause=f"AND priority = '{priority_filter}'" if priority_filter else ""
        )

        result = await session.execute(sa.text(query))
        row = result.fetchone()
        if not row:
            return False

        task_id, task_type, payload, _ = row

        try:
            if task_type == "score_document":
                await _score_document(payload["document_id"], payload["ticker"], session)
            await session.execute(
                sa.text("UPDATE task_queue SET status = 'done', completed_at = now() WHERE task_id = :tid"),
                {"tid": task_id},
            )
        except Exception as exc:
            logger.error("[worker] task %d failed: %s", task_id, exc)
            await session.execute(
                sa.text("UPDATE task_queue SET status = 'failed' WHERE task_id = :tid"),
                {"tid": task_id},
            )
        await session.commit()
        return True


async def _score_document(document_id: int, ticker: str, session: AsyncSession) -> None:
    from config.settings import settings as cfg

    doc = await session.get(RawDocument, document_id)
    if not doc:
        return

    text_body = f"{doc.title or ''}\n\n{doc.body or ''}".strip()
    if not text_body:
        return

    model_key = route_model(doc.source, doc.source_subtype)
    probs = score_text(text_body, model_key)

    raw_score = round(probs["positive_prob"] - probs["negative_prob"], 4)

    # Retrieve source tier weight
    tier_row = await session.execute(
        sa.text("SELECT tier, base_weight FROM source_tiers WHERE source_name = :src"),
        {"src": doc.source},
    )
    tier_info = tier_row.fetchone()
    source_tier = tier_info.tier if tier_info else 3
    source_weight = tier_info.base_weight if tier_info else 0.70

    confidence_mult = 0.7 if doc.source in _SOCIAL_SOURCES else 1.0

    # Engagement multiplier for social posts (from raw_json)
    engagement_mult = 1.0
    if doc.source in _SOCIAL_SOURCES and doc.raw_json:
        upvotes = doc.raw_json.get("score", 0) or 0
        import math
        engagement_mult = min(1.0, math.log(1 + upvotes) / math.log(1 + 500))

    await session.execute(
        sa.text("""
            INSERT INTO sentiment_scores
                (document_id, ticker, model_used, positive_prob, negative_prob, neutral_prob,
                 raw_score, source_tier, source_weight, confidence_mult, engagement_mult, scored_at)
            VALUES
                (:doc_id, :ticker, :model, :pos, :neg, :neu,
                 :raw_score, :tier, :weight, :conf_mult, :eng_mult, now())
        """),
        {
            "doc_id": document_id,
            "ticker": ticker,
            "model": model_key,
            "pos": probs["positive_prob"],
            "neg": probs["negative_prob"],
            "neu": probs["neutral_prob"],
            "raw_score": raw_score,
            "tier": source_tier,
            "weight": source_weight,
            "conf_mult": confidence_mult,
            "eng_mult": engagement_mult,
        },
    )
    logger.debug("[worker] scored doc %d (%s) for %s: %.3f", document_id, model_key, ticker, raw_score)
