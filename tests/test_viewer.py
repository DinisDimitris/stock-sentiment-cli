"""Tests for the analysis viewer card derivation and API payloads."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from viewer import app as viewer_app


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_ANALYSIS_DIR = REPO_ROOT / "output" / "analysis"


def write_bundle(folder: Path, summary_json: dict, summary_text: str = "") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(json.dumps(summary_json), encoding="utf-8")
    if summary_text:
        (folder / "summary.txt").write_text(summary_text, encoding="utf-8")


def touch_age(path: Path, *, hours: float) -> None:
    moment = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    stamp = moment.timestamp()
    for child in path.iterdir():
        os.utime(child, (stamp, stamp))


OK_SUMMARY = {
    "ticker": "AAPL",
    "company_name": "Apple Inc",
    "sector": "Technology",
    "direction": "BULLISH",
    "confidence_pct": 75,
    "summary": "Services momentum offsets hardware softness.",
    "primary_drivers": ["Services growth"],
    "primary_risks": ["China exposure"],
    "conflicts": [],
    "top_events": [],
    "composite_score_1d": 0.2,
    "composite_score_7d": 0.42,
    "composite_score_30d": 0.31,
    "document_count_7d": 120,
    "trend": "improving",
    "source_breakdown": {"tier_1": {"score": 0.4, "count": 3}},
    "macro_overlay": {"score": 0.1, "description": "Neutral", "dominant_factor": "rates"},
}


SUMMARY_TEXT = """AAPL (Apple Inc) | Technology
Direction: BULLISH | Confidence: 75%
Generated: 2026-09-13T09:00:00+00:00
Source: GPT-4o-mini | fresh analysis

Assessment:
Services momentum offsets hardware softness.

Primary drivers:
- Services growth
"""


# --- header stripping (UX-1) -------------------------------------------------


def test_strip_summary_header_returns_assessment_body():
    body = viewer_app.strip_summary_header(SUMMARY_TEXT)
    assert body.startswith("Services momentum")
    assert "Generated:" not in body
    assert "Direction:" not in body
    assert "Assessment:" not in body


def test_strip_summary_header_returns_empty_for_header_only():
    header_only = "\n".join(SUMMARY_TEXT.splitlines()[:4])
    assert viewer_app.strip_summary_header(header_only) == ""


def test_strip_summary_header_leaves_plain_text_untouched():
    assert viewer_app.strip_summary_header("Just a plain note.") == "Just a plain note."


def test_extract_assessment_stops_at_section_heading():
    body = "Services momentum offsets hardware softness.\n\nPrimary drivers:\n- Services growth"
    assert viewer_app.extract_assessment(body) == "Services momentum offsets hardware softness."


def test_extract_assessment_without_sections_returns_body():
    assert viewer_app.extract_assessment("Only prose here.") == "Only prose here."


# --- card derivation (UX-1 / UX-4) -------------------------------------------


def test_build_card_is_fresh_when_just_updated(tmp_path):
    folder = tmp_path / "AAPL"
    write_bundle(folder, OK_SUMMARY, SUMMARY_TEXT)

    card = viewer_app.build_card(folder)

    assert card["status"] == "fresh"
    assert card["assessment"] == "Services momentum offsets hardware softness."
    assert card["direction"] == "BULLISH"
    assert card["coverage"] == {"level": "high", "document_count_7d": 120}
    assert "Generated:" not in card["summary_text_body"]


def test_build_card_is_stale_after_three_days(tmp_path):
    folder = tmp_path / "AAPL"
    write_bundle(folder, OK_SUMMARY, SUMMARY_TEXT)
    touch_age(folder, hours=72)

    card = viewer_app.build_card(folder)

    assert card["status"] == "stale"


def test_build_card_is_recent_between_six_and_twenty_four_hours(tmp_path):
    folder = tmp_path / "AAPL"
    write_bundle(folder, OK_SUMMARY, SUMMARY_TEXT)
    touch_age(folder, hours=12)

    assert viewer_app.build_card(folder)["status"] == "recent"


def test_build_card_reports_failed_run_as_failure(tmp_path):
    folder = tmp_path / "AAPL"
    failed = dict(OK_SUMMARY)
    failed.update({"status": "failed", "error": "provider 404", "direction": "NEUTRAL", "confidence_pct": 0})
    write_bundle(folder, failed, SUMMARY_TEXT)

    card = viewer_app.build_card(folder)

    assert card["status"] == "failed"
    assert card["error_message"] == "provider 404"


def test_build_card_detects_legacy_failure_wording(tmp_path):
    folder = tmp_path / "AAPL"
    legacy = dict(OK_SUMMARY)
    legacy["summary"] = "Agent analysis unavailable: Error code: 404"
    write_bundle(folder, legacy, SUMMARY_TEXT)

    assert viewer_app.build_card(folder)["status"] == "failed"


def test_build_card_without_bundle_is_no_data(tmp_path):
    folder = tmp_path / "EMPTY"
    folder.mkdir()

    card = viewer_app.build_card(folder)

    assert card["status"] == "no_data"
    assert card["assessment"] is None
    assert card["coverage"] == {"level": "unknown", "document_count_7d": None}


def test_build_card_survives_invalid_json(tmp_path):
    folder = tmp_path / "BROKEN"
    folder.mkdir()
    (folder / "summary.json").write_text("{not json", encoding="utf-8")
    (folder / "summary.txt").write_text(SUMMARY_TEXT, encoding="utf-8")

    card = viewer_app.build_card(folder)

    assert card["notes"] == ["summary.json could not be parsed; showing summary.txt instead."]
    assert card["assessment"] == "Services momentum offsets hardware softness."


@pytest.mark.parametrize(
    ("documents", "level"),
    [(None, "unknown"), (0, "low"), (4, "low"), (5, "medium"), (49, "medium"), (50, "high")],
)
def test_coverage_levels(documents, level):
    summary = dict(OK_SUMMARY)
    if documents is None:
        summary.pop("document_count_7d")
    else:
        summary["document_count_7d"] = documents

    assert viewer_app.derive_coverage(summary)["level"] == level


# --- shared payload (UX-3) ---------------------------------------------------


def test_get_stock_card_matches_grid_payload(tmp_path):
    write_bundle(tmp_path / "AAPL", OK_SUMMARY, SUMMARY_TEXT)

    grid = viewer_app.get_stock_cards(tmp_path)
    single = viewer_app.get_stock_card("AAPL", tmp_path)

    assert len(grid) == 1
    assert single == grid[0]


@pytest.mark.parametrize("ticker", ["..", ".hidden", "a/b", "", "  "])
def test_get_stock_card_rejects_unsafe_names(ticker, tmp_path):
    assert viewer_app.get_stock_card(ticker, tmp_path) is None


def test_get_stock_card_returns_none_for_unknown_ticker(tmp_path):
    write_bundle(tmp_path / "AAPL", OK_SUMMARY, SUMMARY_TEXT)
    assert viewer_app.get_stock_card("MSFT", tmp_path) is None


def test_get_stock_cards_on_missing_directory(tmp_path):
    assert viewer_app.get_stock_cards(tmp_path / "does-not-exist") == []


# --- real checked-in bundles (UX-1 acceptance) --------------------------------


@pytest.mark.skipif(not REAL_ANALYSIS_DIR.is_dir(), reason="no checked-in analysis bundles")
def test_checked_in_cards_expose_no_header_artifacts():
    cards = viewer_app.get_stock_cards(REAL_ANALYSIS_DIR)
    assert cards, "expected at least one checked-in analysis bundle"

    for card in cards:
        body = card["summary_text_body"]
        assert "Generated:" not in body, card["ticker"]
        assert "Direction:" not in body, card["ticker"]
        assert "Source:" not in body, card["ticker"]
