"""
Social media text pre-processor. Runs before FinBERT on Reddit and StockTwits content.
Normalises cashtags, expands emojis, expands WSB slang, and normalises ALL_CAPS.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_json(filename: str) -> dict:
    path = _DATA_DIR / filename
    if path.exists():
        return json.loads(path.read_text())
    return {}


_EMOJI_MAP = _load_json("emoji_sentiment_map.json")
_SLANG_MAP = _load_json("financial_slang.json")

# Preserve these ALL_CAPS tokens as signals
_PRESERVE_CAPS = {"BULL", "BEAR", "BUY", "SELL", "LONG", "SHORT", "PUTS", "CALLS", "HOLD", "YOLO"}


def preprocess(text: str) -> str:
    if not text:
        return text

    text = _normalise_cashtags(text)
    text = _expand_emojis(text)
    text = _expand_slang(text)
    text = _normalise_caps(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalise_cashtags(text: str) -> str:
    return re.sub(r"\$([A-Z]{1,5})\b", r"\1", text)


def _expand_emojis(text: str) -> str:
    for emoji, replacement in _EMOJI_MAP.items():
        text = text.replace(emoji, f" {replacement} ")
    return text


def _expand_slang(text: str) -> str:
    # Word-boundary aware replacement (case-insensitive)
    for slang, expansion in _SLANG_MAP.items():
        pattern = rf"\b{re.escape(slang)}\b"
        text = re.sub(pattern, expansion, text, flags=re.IGNORECASE)
    return text


def _normalise_caps(text: str) -> str:
    def _process_word(word: str) -> str:
        clean = re.sub(r"[^A-Z]", "", word.upper())
        if clean in _PRESERVE_CAPS:
            return word.upper()
        return word.lower()

    tokens = text.split()
    return " ".join(_process_word(t) for t in tokens)
