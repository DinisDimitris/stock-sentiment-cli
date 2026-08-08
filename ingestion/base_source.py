"""
Abstract base class for all ingestion sources.
Handles retry logic, rate limiting, and document persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Company, DocumentCompany, RawDocument
from db.session import AsyncSessionLocal
from deduplication.deduplicator import (
    compute_simhash,
    content_hash,
    find_duplicate_by_hash,
    find_or_create_event,
)

logger = logging.getLogger(__name__)


class BaseSource(ABC):
    source_name: str  # must match source_tiers.source_name
    source_weight: float = 1.0

    def __init__(self):
        self._rate_limit_semaphore = asyncio.Semaphore(2)

    @abstractmethod
    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        """Return list of raw item dicts for this ticker."""
        ...

    @abstractmethod
    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """
        Normalise a raw API item into a standard dict with keys:
          url, title, body, published_at, source_subtype, fast_lane
        """
        ...

    async def ingest(self, ticker: str) -> int:
        """Fetch, parse, deduplicate and store documents. Returns count saved."""
        saved = 0
        try:
            items = await self._fetch_with_retry(ticker)
        except Exception as exc:
            logger.error("[%s] fetch failed for %s: %s", self.source_name, ticker, exc)
            return 0

        async with AsyncSessionLocal() as session:
            for raw_item in items:
                try:
                    parsed = self.parse(raw_item)
                    if not parsed.get("url") and not parsed.get("title"):
                        continue

                    url = parsed.get("url")
                    title = parsed.get("title", "")
                    body = parsed.get("body", "")
                    c_hash = content_hash(title, body)

                    # L2: check content hash
                    dup = await find_duplicate_by_hash(c_hash, session)
                    if dup:
                        continue

                    doc = RawDocument(
                        source=self.source_name,
                        source_subtype=parsed.get("source_subtype"),
                        url=url,
                        content_hash=c_hash,
                        title=title,
                        body=body,
                        published_at=parsed.get("published_at"),
                        raw_json=raw_item,
                        fast_lane=parsed.get("fast_lane", False),
                        simhash=compute_simhash(title, body),
                    )
                    session.add(doc)

                    try:
                        await session.flush()  # get doc.id; L1 UNIQUE violation surfaces here
                    except IntegrityError:
                        await session.rollback()
                        continue

                    session.add(DocumentCompany(
                        document_id=doc.id,
                        ticker=ticker,
                        confidence=1.0,
                    ))

                    await find_or_create_event(doc, [ticker], session)

                    # Queue for sentiment processing
                    from db.models import TaskQueue
                    priority = "CRITICAL" if doc.fast_lane else "STANDARD"
                    session.add(TaskQueue(
                        task_type="score_document",
                        priority=priority,
                        payload={"document_id": doc.id, "ticker": ticker},
                    ))

                    saved += 1

                except Exception as exc:
                    logger.warning("[%s] parse/save error: %s", self.source_name, exc)
                    await session.rollback()
                    continue

            await session.commit()

        logger.info("[%s] saved %d documents for %s", self.source_name, saved, ticker)
        return saved

    async def _fetch_with_retry(self, ticker: str, max_retries: int = 3) -> list[dict]:
        delay = 2.0
        for attempt in range(max_retries):
            try:
                async with self._rate_limit_semaphore:
                    return await self.fetch(ticker)
            except Exception as exc:
                if attempt == max_retries - 1:
                    raise
                logger.warning("[%s] retry %d for %s: %s", self.source_name, attempt + 1, ticker, exc)
                await asyncio.sleep(delay)
                delay *= 2
        return []
