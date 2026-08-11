from __future__ import annotations

import json
from pathlib import Path


def write_analysis_output(result: dict, base_dir: str | Path | None = None) -> list[Path]:
    ticker = result.get("ticker")
    if not ticker:
        raise ValueError("result must include a ticker")

    root_dir = Path(base_dir) if base_dir is not None else Path("output") / "analysis"
    company_dir = root_dir / ticker
    company_dir.mkdir(parents=True, exist_ok=True)

    text_path = company_dir / "summary.txt"
    json_path = company_dir / "summary.json"

    text_path.write_text(_format_text(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")

    return [text_path, json_path]


def _format_text(result: dict) -> str:
    from .formatter import format_summary_text

    return format_summary_text(result)
