from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
ANALYSIS_DIR = Path(os.environ.get("ANALYSIS_DIR", "/analysis")).resolve()


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


def get_stock_cards() -> list[dict]:
    if not ANALYSIS_DIR.exists() or not ANALYSIS_DIR.is_dir():
        return []

    cards: list[dict] = []

    for folder in sorted(ANALYSIS_DIR.iterdir(), key=lambda item: item.name):
        if not folder.is_dir():
            continue

        summary_text_path = folder / "summary.txt"
        summary_json_path = folder / "summary.json"
        summary_text = read_text_if_present(summary_text_path)
        summary_json = read_json_if_present(summary_json_path)

        modified_values = [
            path.stat().st_mtime
            for path in (summary_text_path, summary_json_path)
            if path.exists() and path.is_file()
        ]

        cards.append(
            {
                "ticker": folder.name,
                "folder_name": folder.name,
                "summary_text": summary_text,
                "summary_json": summary_json,
                "last_updated": iso_timestamp(max(modified_values)) if modified_values else None,
            }
        )

    return cards


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
    server = ThreadingHTTPServer(("0.0.0.0", 8000), StockAnalysisHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()