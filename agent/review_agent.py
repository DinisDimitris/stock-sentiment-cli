"""
Three-step agentic review chain using OpenAI or Anthropic.
Results cached per ticker for 6 hours. Invalidated on CRITICAL fast-lane events.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from agent.context_builder import build_context
from agent.llm_client import get_client, get_default_model, get_escalation_model
from agent.prompts import (
    STEP1_CONFLICT_SYSTEM, STEP1_CONFLICT_USER,
    STEP2_SYNTHESIS_SYSTEM, STEP2_SYNTHESIS_USER,
)
from config.settings import settings
from db.models import AnalysisRun
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def run_review(ticker: str, force_refresh: bool = False) -> dict:
    """
    Run the full agentic review for a ticker.
    Returns the analysis dict; uses cache if valid.
    """
    if not force_refresh:
        cached = await _get_cached(ticker)
        if cached:
            logger.info("[agent] returning cached analysis for %s", ticker)
            return cached

    context = await build_context(ticker)
    if not context:
        raise RuntimeError(f"No context available for {ticker}; cannot run review")
    context_json = json.dumps(context, indent=2, default=str)

    # Step 1: Conflict detection
    conflicts = await _step1_conflicts(context, context_json)

    # Step 2: Synthesis
    synthesis = await _step2_synthesis(context, context_json, conflicts)

    # Merge context scores into result
    result = {
        "ticker": ticker,
        "company_name": context.get("company_name"),
        "sector": context.get("sector"),
        "direction": synthesis.get("direction", "NEUTRAL"),
        "confidence_pct": synthesis.get("confidence_pct", 50),
        "summary": synthesis.get("summary", ""),
        "primary_drivers": synthesis.get("primary_drivers", []),
        "primary_risks": synthesis.get("primary_risks", []),
        "conflicts": conflicts,
        "composite_score_1d": context.get("sentiment_1d"),
        "composite_score_7d": context.get("sentiment_7d"),
        "composite_score_30d": context.get("sentiment_30d"),
        "trend": context.get("trend"),
        "top_events": context.get("top_events", []),
        "source_breakdown": context.get("source_breakdown", {}),
        "macro_overlay": context.get("macro_overlay", {}),
        "viral_alert": context.get("viral_alert", False),
        "document_count_7d": context.get("document_count_7d", 0),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    if result.get("summary") and "Agent analysis unavailable" in result.get("summary", ""):
        logger.warning("[agent] skipping cache write for %s because the model response was unavailable", ticker)
        return result

    await _store_result(ticker, result, context)
    return result


async def _step1_conflicts(context: dict, context_json: str) -> list[dict]:
    client = get_client()
    prompt = STEP1_CONFLICT_USER.format(
        ticker=context["ticker"],
        company_name=context["company_name"],
        context_json=context_json,
    )
    try:
        resp = await client.chat.completions.create(
            model=get_default_model(),
            messages=[
                {"role": "system", "content": STEP1_CONFLICT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0.1,
        )
        data = json.loads(resp.choices[0].message.content)
        conflicts = data.get("conflicts", [])
        logger.info("[agent] step1: %d conflicts detected", len(conflicts))
        return conflicts
    except Exception as exc:
        logger.warning("[agent] step1 failed: %s", exc)
        return []


async def _step2_synthesis(
    context: dict, context_json: str, conflicts: list[dict]
) -> dict:
    client = get_client()

    # Escalate to larger model if many high-severity conflicts
    high_conflicts = [c for c in conflicts if c.get("severity") == "HIGH"]
    model = (
        get_escalation_model()
        if len(conflicts) > 3 or len(high_conflicts) > 1
        else get_default_model()
    )
    if model == get_escalation_model():
        logger.info("[agent] step2: escalating to %s", model)

    prompt = STEP2_SYNTHESIS_USER.format(
        ticker=context["ticker"],
        company_name=context["company_name"],
        sector=context.get("sector", "Unknown"),
        context_json=context_json,
        conflicts_json=json.dumps(conflicts, indent=2),
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": STEP2_SYNTHESIS_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=500,
            temperature=0.2,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.warning("[agent] step2 failed: %s", exc)
        return {
            "direction": "NEUTRAL",
            "confidence_pct": 0,
            "summary": f"Agent analysis unavailable: {exc}",
            "primary_drivers": [],
            "primary_risks": [],
        }


async def _get_cached(ticker: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            sa.text("""
                SELECT run_id, composite_score_1d, composite_score_7d, composite_score_30d,
                       direction, confidence_pct, agent_summary, raw_agent_response, expires_at
                FROM analysis_runs
                WHERE ticker = :t AND expires_at > now()
                ORDER BY requested_at DESC
                LIMIT 1
            """),
            {"t": ticker},
        )
        record = row.fetchone()
        if record and record.raw_agent_response:
            result = dict(record.raw_agent_response)
            result["_from_cache"] = True
            result["_expires_at"] = record.expires_at.isoformat() if record.expires_at else None
            return result
    return None


async def _store_result(ticker: str, result: dict, context: dict) -> None:
    expires = datetime.now(tz=timezone.utc) + timedelta(seconds=settings.agent_cache_ttl)
    async with AsyncSessionLocal() as session:
        session.add(AnalysisRun(
            ticker=ticker,
            composite_score_1d=result.get("composite_score_1d"),
            composite_score_7d=result.get("composite_score_7d"),
            composite_score_30d=result.get("composite_score_30d"),
            direction=result.get("direction"),
            confidence_pct=result.get("confidence_pct"),
            agent_summary=result.get("summary"),
            raw_agent_response=result,
            expires_at=expires,
        ))
        await session.commit()


async def invalidate_cache(ticker: str) -> None:
    """Called when a CRITICAL fast-lane event arrives for ticker."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa.text("UPDATE analysis_runs SET expires_at = now() WHERE ticker = :t"),
            {"t": ticker},
        )
        await session.commit()
