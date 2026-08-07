"""Tests for FinBERT router label normalisation and model routing logic."""

import pytest
from processing.router import route_model, _normalise_labels, _blend


def test_route_8k_to_dual():
    assert route_model("sec_edgar", "8-K") == "dual_fls_general"


def test_route_def14a_to_esg():
    assert route_model("sec_edgar", "DEF 14A") == "finbert_esg"


def test_route_company_ir_to_tone():
    assert route_model("company_ir", "press_release") == "finbert_tone"


def test_route_reddit_to_social():
    assert route_model("reddit_stocks", "reddit_post") == "social_finbert_general"


def test_route_wsb_to_social():
    assert route_model("reddit_wsb", "reddit_post") == "social_finbert_general"


def test_route_yahoo_to_general():
    assert route_model("yahoo_finance", "news") == "finbert_general"


def test_route_unknown_falls_back_to_general():
    assert route_model("some_unknown_source", "some_subtype") == "finbert_general"


def test_normalise_labels_general():
    raw = [
        {"label": "positive", "score": 0.7},
        {"label": "negative", "score": 0.2},
        {"label": "neutral", "score": 0.1},
    ]
    result = _normalise_labels(raw, "finbert_general")
    assert abs(result["positive_prob"] - 0.7) < 0.01
    assert abs(result["negative_prob"] - 0.2) < 0.01
    assert abs(result["neutral_prob"] - 0.1) < 0.01


def test_normalise_labels_tone_uppercase():
    raw = [
        {"label": "Positive", "score": 0.6},
        {"label": "Negative", "score": 0.3},
        {"label": "Neutral", "score": 0.1},
    ]
    result = _normalise_labels(raw, "finbert_tone")
    assert abs(result["positive_prob"] - 0.6) < 0.01


def test_normalise_labels_fls():
    raw = [
        {"label": "Forward-looking", "score": 0.8},
        {"label": "Not-forward-looking", "score": 0.2},
    ]
    result = _normalise_labels(raw, "finbert_fls")
    # Should produce some sentiment distribution, not crash
    assert "positive_prob" in result
    total = result["positive_prob"] + result["negative_prob"] + result["neutral_prob"]
    assert abs(total - 1.0) < 0.01


def test_blend():
    a = {"positive_prob": 0.8, "negative_prob": 0.1, "neutral_prob": 0.1}
    b = {"positive_prob": 0.4, "negative_prob": 0.4, "neutral_prob": 0.2}
    result = _blend(a, b, weight_a=0.6, weight_b=0.4)
    expected_pos = 0.8 * 0.6 + 0.4 * 0.4
    assert abs(result["positive_prob"] - expected_pos) < 0.01
