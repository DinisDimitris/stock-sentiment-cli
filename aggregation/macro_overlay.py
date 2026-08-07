"""
Macro overlay: converts FRED time-series indicators into a sector-adjusted
macro sentiment score S_macro ∈ [-1, +1].
Uses z-score normalisation against 12-month rolling distributions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import sqlalchemy as sa
import yaml

from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "sector_macro_weights.yaml"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        return yaml.safe_load(_CONFIG_PATH.read_text())
    return {}


async def compute_macro_score(sector: str | None) -> dict:
    """
    Return {'score': float, 'dominant_factor': str, 'description': str}.
    score ∈ [-1, +1] where positive = macro tailwind, negative = macro headwind.
    """
    config = _load_config()
    weights_by_sector = config.get("sectors", {})
    sector_key = (sector or "").replace(" ", "_").replace("/", "_")
    weights = weights_by_sector.get(sector_key) or weights_by_sector.get("Default", {})

    if not weights:
        return {"score": 0.0, "dominant_factor": "no_macro_config", "description": "Macro data unavailable"}

    async with AsyncSessionLocal() as session:
        indicator_scores = {}
        for indicator_code in weights:
            z = await _compute_z_score(indicator_code, session)
            if z is not None:
                # Clamp to [-2, 2] then normalise to [-1, 1]
                clamped = max(-2.0, min(2.0, z))
                indicator_scores[indicator_code] = clamped / 2.0

    if not indicator_scores:
        return {"score": 0.0, "dominant_factor": "no_data", "description": "No FRED data ingested yet"}

    total_weight = 0.0
    weighted_sum = 0.0
    for code, weight in weights.items():
        if code in indicator_scores:
            weighted_sum += indicator_scores[code] * weight
            total_weight += weight

    score = round(weighted_sum / total_weight, 4) if total_weight else 0.0

    dominant = max(indicator_scores, key=lambda k: abs(indicator_scores[k]))
    description = _describe_macro(score, dominant)

    return {"score": score, "dominant_factor": dominant, "description": description}


async def _compute_z_score(indicator_code: str, session) -> Optional[float]:
    """Compute (current - 12m_mean) / 12m_std for an indicator."""
    rows = await session.execute(
        sa.text("""
            SELECT value, released_at FROM macro_indicators
            WHERE indicator_code = :code
            ORDER BY released_at DESC
            LIMIT 366
        """),
        {"code": indicator_code},
    )
    records = rows.fetchall()
    if len(records) < 2:
        return None

    values = [r.value for r in records]
    current = values[0]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = variance ** 0.5

    if std == 0:
        return 0.0

    # For some indicators, higher = bearish (e.g., Fed Funds Rate, CPI, Unemployment)
    bearish_indicators = {"DFF", "CPIAUCSL", "UNRATE", "VIXCLS"}
    z = (current - mean) / std
    if indicator_code in bearish_indicators:
        z = -z  # invert: rising rate/inflation/unemployment = macro headwind

    return round(z, 4)


def _describe_macro(score: float, dominant: str) -> str:
    indicator_names = {
        "DFF": "interest rates",
        "CPIAUCSL": "inflation",
        "UNRATE": "unemployment",
        "T10Y2Y": "yield curve",
        "VIXCLS": "market volatility",
        "INDPRO": "industrial production",
        "DCOILWTICO": "oil prices",
    }
    indicator_label = indicator_names.get(dominant, dominant)

    if score > 0.2:
        return f"Macro tailwind ({indicator_label} favourable)"
    if score < -0.2:
        return f"Macro headwind ({indicator_label} unfavourable)"
    return f"Macro neutral ({indicator_label} near historical average)"
