from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_ANALYSIS_DIR = ROOT.parent / "output" / "analysis"
ANALYSIS_DIR = Path(os.environ.get("ANALYSIS_DIR", str(DEFAULT_ANALYSIS_DIR))).resolve()
VIEWER_PORT = int(os.environ.get("VIEWER_PORT", "8000"))

# Card freshness thresholds, in seconds.
FRESH_WITHIN_SECONDS = int(os.environ.get("VIEWER_FRESH_WITHIN_SECONDS", "21600"))  # 6 hours
STALE_AFTER_SECONDS = int(os.environ.get("VIEWER_STALE_AFTER_SECONDS", "86400"))  # 24 hours

# Evidence coverage thresholds, counted as documents in the trailing 7 days.
LOW_COVERAGE_DOCS = int(os.environ.get("VIEWER_LOW_COVERAGE_DOCS", "5"))
HIGH_COVERAGE_DOCS = int(os.environ.get("VIEWER_HIGH_COVERAGE_DOCS", "50"))

# Substrings that mark a stored bundle as a failed agent run rather than an opinion.
FAILED_MARKERS = ("analysis unavailable",)

# Prefixes that belong to the summary.txt file header, not to the assessment body.
HEADER_PREFIXES = ("generated:", "source:", "direction:", "confidence:", "assessment:")

# Section headings that terminate the free-text assessment inside summary.txt.
SECTION_LABELS = ("primary drivers:", "primary risks:", "conflicts:", "top events:")


def iso_timestamp(value: float | None = None) -> str:
    moment = datetime.fromtimestamp(value, tz=timezone.utc) if value else datetime.now(timezone.utc)
    return moment.isoformat()


def read_text_if_present(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def read_json_if_present(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_error": "Invalid JSON"}

    return data if isinstance(data, dict) else {"_value": data}


def strip_summary_header(text: str) -> str:
    """Return the assessment body of a summary.txt, without its metadata header.

    summary.txt starts with four generated lines (ticker, direction, generated, source)
    followed by a blank line and an optional "Assessment:" label. The viewer must never
    display that header, because it is identical across every ticker in a run.
    """
    text = (text or "").strip()
    if not text:
        return ""

    lines = text.splitlines()
    has_header = any(
        line.strip().lower().startswith(HEADER_PREFIXES) for line in lines[:5]
    )
    if not has_header:
        return text

    blank_index = next((index for index, line in enumerate(lines) if not line.strip()), None)
    if blank_index is None:
        # Header only: there is no assessment body to show.
        return ""

    body = lines[blank_index + 1:]
    if body and body[0].strip().lower().rstrip(":") == "assessment":
        body = body[1:]
    return "\n".join(body).strip()


def extract_assessment(body: str) -> str:
    """Take just the assessment paragraph from a summary.txt body.

    The body continues with "Primary drivers:" / "Primary risks:" sections; those are
    rendered separately from structured data, so the prose must stop before them.
    """
    text = (body or "").strip()
    if not text:
        return ""

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() in SECTION_LABELS:
            return "\n".join(lines[:index]).strip()
    return text


def _as_document_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def derive_coverage(summary_json: dict) -> dict:
    documents = _as_document_count(summary_json.get("document_count_7d"))
    if documents is None:
        level = "unknown"
    elif documents < LOW_COVERAGE_DOCS:
        level = "low"
    elif documents >= HIGH_COVERAGE_DOCS:
        level = "high"
    else:
        level = "medium"
    return {"level": level, "document_count_7d": documents}


def card_is_failed(summary_json: dict, summary_text: str) -> bool:
    if summary_json.get("status") == "failed":
        return True

    candidates = [summary_text, summary_json.get("summary"), summary_json.get("error")]
    for candidate in candidates:
        if isinstance(candidate, str) and any(
            marker in candidate.lower() for marker in FAILED_MARKERS
        ):
            return True
    return False


def derive_status(
    *,
    summary_json: dict,
    summary_text: str,
    assessment: str | None,
    last_updated: datetime | None,
    now: datetime,
) -> str:
    if not summary_json and not summary_text:
        return "no_data"
    if card_is_failed(summary_json, summary_text):
        return "failed"
    if last_updated is None:
        return "no_data"
    if not summary_json and not assessment:
        return "no_data"

    age_seconds = (now - last_updated).total_seconds()
    if age_seconds <= FRESH_WITHIN_SECONDS:
        return "fresh"
    if age_seconds >= STALE_AFTER_SECONDS:
        return "stale"
    return "recent"


def build_card(folder: Path, *, now: datetime | None = None) -> dict:
    """Build the single shared payload used by both the board and the detail view."""
    now = now or datetime.now(timezone.utc)

    summary_text_path = folder / "summary.txt"
    summary_json_path = folder / "summary.json"
    summary_text = read_text_if_present(summary_text_path)
    summary_json = read_json_if_present(summary_json_path)
    summary_text_body = strip_summary_header(summary_text)

    modified_values = [
        path.stat().st_mtime
        for path in (summary_text_path, summary_json_path)
        if path.exists() and path.is_file()
    ]
    last_updated_value = max(modified_values) if modified_values else None
    last_updated = (
        datetime.fromtimestamp(last_updated_value, tz=timezone.utc)
        if last_updated_value
        else None
    )

    assessment = summary_json.get("summary")
    if not isinstance(assessment, str) or not assessment.strip():
        assessment = extract_assessment(summary_text_body) or None
    else:
        assessment = assessment.strip()

    error_message = summary_json.get("error")
    if not isinstance(error_message, str) or not error_message.strip():
        error_message = assessment if card_is_failed(summary_json, summary_text) else None

    direction = summary_json.get("direction")
    direction = direction.strip().upper() if isinstance(direction, str) and direction.strip() else None

    notes: list[str] = []
    if summary_json.get("_error"):
        notes.append("summary.json could not be parsed; showing summary.txt instead.")

    return {
        "ticker": folder.name,
        "folder_name": folder.name,
        "summary_text": summary_text,
        "summary_text_body": summary_text_body,
        "summary_json": summary_json,
        "last_updated": iso_timestamp(last_updated_value) if last_updated_value else None,
        "status": derive_status(
            summary_json=summary_json,
            summary_text=summary_text,
            assessment=assessment,
            last_updated=last_updated,
            now=now,
        ),
        "assessment": assessment,
        "error_message": error_message,
        "direction": direction,
        "coverage": derive_coverage(summary_json),
        "model": summary_json.get("llm_model") if isinstance(summary_json.get("llm_model"), str) else None,
        "from_cache": bool(summary_json.get("_from_cache", False)),
        "notes": notes,
    }


def get_stock_cards(base_dir: Path | None = None) -> list[dict]:
    directory = Path(base_dir) if base_dir is not None else ANALYSIS_DIR
    if not directory.exists() or not directory.is_dir():
        return []

    cards = [
        build_card(folder)
        for folder in sorted(directory.iterdir(), key=lambda item: item.name)
        if folder.is_dir()
    ]
    return cards


def get_stock_card(ticker: str, base_dir: Path | None = None) -> dict | None:
    directory = Path(base_dir) if base_dir is not None else ANALYSIS_DIR
    candidate = (ticker or "").strip()

    # Reject anything that is not a single, non-hidden path segment.
    if not candidate or candidate.startswith(".") or candidate != Path(candidate).name:
        return None

    folder = directory / candidate
    if not folder.is_dir():
        return None
    return build_card(folder)


class StockAnalysisHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/stocks":
            self.respond_json(
                {
                    "analysis_path": str(ANALYSIS_DIR),
                    "refreshed_at": iso_timestamp(),
                    "stocks": get_stock_cards(),
                }
            )
            return

        if parsed.path.startswith("/api/stocks/"):
            ticker = unquote(parsed.path[len("/api/stocks/"):])
            card = get_stock_card(ticker)
            if card is None:
                self.respond_json(
                    {
                        "error": {
                            "code": "ticker_not_found",
                            "message": f"No analysis bundle found for '{ticker}'.",
                        }
                    },
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self.respond_json(card)
            return

        self.serve_static(parsed.path)

    def serve_static(self, path: str) -> None:
        requested = path.lstrip("/") or "index.html"
        file_path = (ROOT / requested).resolve()

        if ROOT not in file_path.parents and file_path != ROOT:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(file_path.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def respond_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", VIEWER_PORT), StockAnalysisHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
