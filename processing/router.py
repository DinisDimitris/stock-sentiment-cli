"""
FinBERT routing: maps source+subtype to the appropriate model,
runs inference with chunking, normalises labels, and writes to sentiment_scores.
"""

from __future__ import annotations

import logging
from typing import Any

from processing.chunker import chunk_and_weight
from processing.model_registry import get_model
from processing.social_preprocessor import preprocess

logger = logging.getLogger(__name__)


# Routing table: (source, source_subtype) → model_key
# None subtype means "any subtype from this source"
_ROUTING: list[tuple[str | None, str | None, str]] = [
    # SEC filings — run BOTH fls and general, weighted average
    ("sec_edgar", "8-K", "dual_fls_general"),
    ("sec_edgar", "10-Q", "dual_fls_general"),
    ("sec_edgar", "10-K", "dual_fls_general"),
    ("sec_edgar", "13D", "dual_fls_general"),
    ("sec_edgar", "13G", "dual_fls_general"),
    ("sec_edgar", "DEF 14A", "finbert_esg"),
    # Executive communications
    ("company_ir", None, "finbert_tone"),
    ("finnhub_transcripts", None, "finbert_tone"),
    # Social media — needs preprocessing first
    ("reddit_stocks", None, "social_finbert_general"),
    ("reddit_wsb", None, "social_finbert_general"),
    ("stocktwits", None, "social_finbert_general"),
    # Macro / general news
    ("federal_reserve", None, "finbert_general"),
    ("yahoo_finance", None, "finbert_general"),
    ("finnhub_news", None, "finbert_general"),
    ("ap_news", None, "finbert_general"),
]


def route_model(source: str, source_subtype: str | None) -> str:
    for src, sub, model in _ROUTING:
        if src == source or src is None:
            if sub is None or sub == source_subtype:
                return model
    return "finbert_general"


def score_text(text: str, model_key: str) -> dict[str, float]:
    """
    Score text using the selected model. Returns normalised
    {positive_prob, negative_prob, neutral_prob}.
    Handles chunking and label normalisation.
    """
    is_social = model_key == "social_finbert_general"
    actual_key = "finbert_general" if is_social else model_key
    is_dual = model_key == "dual_fls_general"

    if is_social:
        text = preprocess(text)

    if is_dual:
        fls_scores = _score_single(text, "finbert_fls")
        gen_scores = _score_single(text, "finbert_general")
        return _blend(fls_scores, gen_scores, weight_a=0.6, weight_b=0.4)

    return _score_single(text, actual_key)


def _score_single(text: str, model_key: str) -> dict[str, float]:
    """Score text with chunking; return weighted average across chunks."""
    model = get_model(model_key)
    chunks = chunk_and_weight(text)
    if not chunks:
        return {"positive_prob": 0.33, "negative_prob": 0.33, "neutral_prob": 0.34}

    pos_acc = neg_acc = neu_acc = 0.0
    for chunk_text, weight in chunks:
        raw_output = model(chunk_text)
        probs = _normalise_labels(raw_output[0], model_key)
        pos_acc += probs["positive_prob"] * weight
        neg_acc += probs["negative_prob"] * weight
        neu_acc += probs["neutral_prob"] * weight

    return {
        "positive_prob": round(pos_acc, 4),
        "negative_prob": round(neg_acc, 4),
        "neutral_prob": round(neu_acc, 4),
    }


def _normalise_labels(raw_labels: list[dict], model_key: str) -> dict[str, float]:
    """
    Map each model's label schema to canonical (positive_prob, negative_prob, neutral_prob).
    finbert_general: labels 'positive', 'negative', 'neutral'
    finbert_tone:    labels 'Positive', 'Negative', 'Neutral'
    finbert_fls:     labels 'Forward-looking', 'Not-forward-looking' → proxy via tone
    finbert_esg:     labels 'positive', 'negative', 'neutral'
    """
    label_map: dict[str, str] = {}

    if model_key == "finbert_fls":
        # FLS model classifies whether text is forward-looking, not sentiment.
        # Treat 'Forward-looking' as a mild positive signal (companies guide upward ~60% of time).
        for item in raw_labels:
            label = item["label"].lower()
            score = item["score"]
            if "not" in label:
                label_map["neutral"] = label_map.get("neutral", 0) + score
            else:
                label_map["positive"] = label_map.get("positive", 0) + score * 0.6
                label_map["negative"] = label_map.get("negative", 0) + score * 0.4
    else:
        for item in raw_labels:
            label = item["label"].lower()
            score = item["score"]
            if label in ("positive", "pos"):
                label_map["positive"] = score
            elif label in ("negative", "neg"):
                label_map["negative"] = score
            else:
                label_map["neutral"] = score

    pos = label_map.get("positive", 0.0)
    neg = label_map.get("negative", 0.0)
    neu = label_map.get("neutral", 0.0)
    total = pos + neg + neu or 1.0
    return {
        "positive_prob": pos / total,
        "negative_prob": neg / total,
        "neutral_prob": neu / total,
    }


def _blend(a: dict, b: dict, weight_a: float, weight_b: float) -> dict:
    total = weight_a + weight_b
    return {
        "positive_prob": round((a["positive_prob"] * weight_a + b["positive_prob"] * weight_b) / total, 4),
        "negative_prob": round((a["negative_prob"] * weight_a + b["negative_prob"] * weight_b) / total, 4),
        "neutral_prob": round((a["neutral_prob"] * weight_a + b["neutral_prob"] * weight_b) / total, 4),
    }
