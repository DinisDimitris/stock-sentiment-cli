from __future__ import annotations

import json

from output.persistence import write_analysis_output


def test_write_analysis_output_creates_company_folder_and_files(tmp_path):
    result = {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "sector": "Technology",
        "direction": "BULLISH",
        "confidence_pct": 87,
        "summary": "Strong momentum and improving fundamentals.",
        "primary_drivers": ["Revenue growth"],
        "primary_risks": ["Valuation"],
        "generated_at": "2026-08-08T22:09:40.756000+00:00",
    }

    paths = write_analysis_output(result, base_dir=tmp_path)

    assert len(paths) == 2
    assert paths[0].parent == tmp_path / "AAPL"
    assert paths[0].suffix == ".txt"
    assert paths[1].suffix == ".json"
    assert paths[0].exists()
    assert paths[1].exists()

    text = paths[0].read_text(encoding="utf-8")
    data = json.loads(paths[1].read_text(encoding="utf-8"))

    assert "AAPL (Apple Inc.) | Technology" in text
    assert "Strong momentum and improving fundamentals." in text
    assert data["ticker"] == "AAPL"
    assert data["summary"] == "Strong momentum and improving fundamentals."
