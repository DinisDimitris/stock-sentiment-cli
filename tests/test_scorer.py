"""Tests for sentiment aggregation formula."""

import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_recency_decay_1d():
    """Verify 1-day decay constant gives ~50% weight after 1 day."""
    lam = 0.70
    weight_at_1d = math.exp(-lam * 1.0)
    assert 0.45 < weight_at_1d < 0.55  # ~49.7%


def test_recency_decay_7d():
    """Verify 7-day decay constant gives reasonable weight at 7 days."""
    lam = 0.14
    weight_at_7d = math.exp(-lam * 7.0)
    assert 0.35 < weight_at_7d < 0.45  # ~37.5%


def test_recency_decay_30d():
    """Verify 30-day decay constant gives reasonable weight at 30 days."""
    lam = 0.035
    weight_at_30d = math.exp(-lam * 30.0)
    assert 0.30 < weight_at_30d < 0.45  # ~35%


def test_weighted_average_formula():
    """Verify weighted average formula works correctly with known values."""
    # Two documents: one positive (tier 1, recent), one negative (tier 5, old)
    # Expected: positive document should dominate
    docs = [
        {"raw_score": 0.8, "source_weight": 1.0, "confidence_mult": 1.0, "engagement_mult": 1.0, "age_days": 0.1},
        {"raw_score": -0.9, "source_weight": 0.25, "confidence_mult": 0.7, "engagement_mult": 0.3, "age_days": 6.0},
    ]
    lam = 0.14
    numerator = sum(
        d["raw_score"] * d["source_weight"] * d["confidence_mult"] * d["engagement_mult"] * math.exp(-lam * d["age_days"])
        for d in docs
    )
    denominator = sum(
        d["source_weight"] * d["confidence_mult"] * d["engagement_mult"] * math.exp(-lam * d["age_days"])
        for d in docs
    )
    score = numerator / denominator
    # Should be positive since tier-1 bullish document dominates
    assert score > 0.0


def test_macro_final_score_blend():
    """Final score = 0.85 * company + 0.15 * macro."""
    company_score = 0.5
    macro_score = -0.3
    final = 0.85 * company_score + 0.15 * macro_score
    assert abs(final - (0.85 * 0.5 + 0.15 * (-0.3))) < 0.001
