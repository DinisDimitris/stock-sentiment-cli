"""
Deduplication at three levels:
  L1: URL unique constraint (handled by DB, caught as exception)
  L2: SHA-256 content hash (cross-source syndication)
  L3: SimHash event clustering (same event, multiple sources)
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from simhash import Simhash
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Event, EventDocument, RawDocument


SIMHASH_BITS = 64
SIMHASH_MASK = (1 << SIMHASH_BITS) - 1
SIGNED_SIMHASH_MAX = 1 << 63


def normalise_text(title: str, body: str) -> str:
    combined = f"{title or ''} {body or ''}"
    combined = re.sub(r"\s+", " ", combined).strip().lower()
    combined = re.sub(r"[^\w\s]", "", combined)
    return combined


def content_hash(title: str, body: str) -> str:
    return hashlib.sha256(normalise_text(title, body).encode()).hexdigest()


def _to_signed_64bit(value: int) -> int:
    unsigned_value = value & SIMHASH_MASK
    if unsigned_value >= SIGNED_SIMHASH_MAX:
        return unsigned_value - (1 << SIMHASH_BITS)
    return unsigned_value


def compute_simhash(title: str, body: str) -> int:
    text_input = f"{title or ''} {(body or '')[:200]}"
    return _to_signed_64bit(Simhash(text_input).value)


def hamming_distance(a: int, b: int) -> int:
    a_bits = _to_signed_64bit(a) & SIMHASH_MASK
    b_bits = _to_signed_64bit(b) & SIMHASH_MASK
    return bin(a_bits ^ b_bits).count("1")


async def find_duplicate_by_hash(
    hash_val: str, session: AsyncSession
) -> Optional[int]:
    """Return existing document_id if content hash matches."""
    row = await session.execute(
        select(RawDocument.id).where(RawDocument.content_hash == hash_val)
    )
    return row.scalar_one_or_none()


async def find_or_create_event(
    document: RawDocument,
    tickers: list[str],
    session: AsyncSession,
) -> int:
    """
    Find an existing event within 24 hours sharing a simhash close to this
    document's simhash (Hamming ≤ 3) and at least one overlapping ticker.
    If found, link document to it. Otherwise create a new event.
    Returns event_id.
    """
    if not document.simhash:
        return await _create_event(document, session)

    cutoff = text(
        "created_at >= :ts"
    ).bindparams(
        ts=document.published_at
    ) if document.published_at else text("1=1")

    rows = await session.execute(
        select(Event.event_id, Event.simhash, Event.headline)
        .where(Event.simhash.isnot(None))
        .order_by(Event.created_at.desc())
        .limit(500)
    )
    candidates = rows.fetchall()

    for row in candidates:
        if row.simhash and hamming_distance(document.simhash, row.simhash) <= 3:
            event_id = row.event_id
            session.add(EventDocument(event_id=event_id, document_id=document.id))
            return event_id

    return await _create_event(document, session)


async def _create_event(document: RawDocument, session: AsyncSession) -> int:
    event_type = _infer_event_type(document.source_subtype or "")
    importance = _infer_importance(document.source, document.source_subtype or "")
    event = Event(
        event_type=event_type,
        headline=document.title or "(no title)",
        importance=importance,
        simhash=document.simhash,
    )
    session.add(event)
    await session.flush()
    session.add(EventDocument(event_id=event.event_id, document_id=document.id))
    return event.event_id


def _infer_event_type(subtype: str) -> str:
    mapping = {
        "8-K": "sec_filing",
        "10-Q": "sec_filing",
        "10-K": "sec_filing",
        "13D": "sec_filing",
        "13G": "sec_filing",
        "DEF 14A": "sec_filing",
        "earnings_call": "earnings",
        "press_release": "press_release",
        "reddit_post": "social",
        "stocktwits_post": "social",
    }
    return mapping.get(subtype, "news")


def _infer_importance(source: str, subtype: str) -> str:
    if source == "sec_edgar" and subtype in ("8-K", "13D", "13G"):
        return "CRITICAL"
    if source == "sec_edgar":
        return "HIGH"
    if source in ("company_ir", "finnhub_transcripts"):
        return "HIGH"
    if source in ("yahoo_finance", "finnhub_news", "ap_news"):
        return "MEDIUM"
    return "LOW"
