"""
Document chunker: splits long text into overlapping 400-token windows
to stay within FinBERT's 512-token limit.
"""

from __future__ import annotations

import re
from typing import Generator

try:
    import nltk
    nltk.data.find("tokenizers/punkt_tab")
    _NLTK_AVAILABLE = True
except (LookupError, Exception):
    try:
        import nltk
        nltk.download("punkt_tab", quiet=True)
        _NLTK_AVAILABLE = True
    except Exception:
        _NLTK_AVAILABLE = False


MAX_TOKENS = 400
STRIDE_TOKENS = 100


def _rough_token_count(text: str) -> int:
    """Approximate token count by whitespace splitting (close enough for chunking)."""
    return len(text.split())


def _sentence_tokenize(text: str) -> list[str]:
    if _NLTK_AVAILABLE:
        from nltk.tokenize import sent_tokenize
        return sent_tokenize(text)
    # Fallback: split on period followed by whitespace + capital
    return re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)


def chunk_text(text: str) -> list[str]:
    """
    Split text into overlapping chunks of ~MAX_TOKENS tokens.
    Returns a list of chunk strings.
    """
    if not text:
        return []

    if _rough_token_count(text) <= MAX_TOKENS:
        return [text]

    sentences = _sentence_tokenize(text)
    chunks: list[str] = []
    current_sentences: list[str] = []
    current_count = 0

    for sentence in sentences:
        s_count = _rough_token_count(sentence)
        if current_count + s_count > MAX_TOKENS and current_sentences:
            chunks.append(" ".join(current_sentences))
            # Stride: keep last STRIDE_TOKENS worth of sentences
            overlap = []
            overlap_count = 0
            for s in reversed(current_sentences):
                sc = _rough_token_count(s)
                if overlap_count + sc > STRIDE_TOKENS:
                    break
                overlap.insert(0, s)
                overlap_count += sc
            current_sentences = overlap
            current_count = overlap_count

        current_sentences.append(sentence)
        current_count += s_count

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return chunks or [text[:2000]]  # hard fallback


def chunk_and_weight(text: str) -> list[tuple[str, float]]:
    """Return list of (chunk_text, weight) tuples. Weights are proportional to chunk length."""
    chunks = chunk_text(text)
    if not chunks:
        return []
    lengths = [_rough_token_count(c) for c in chunks]
    total = sum(lengths) or 1
    return [(chunk, length / total) for chunk, length in zip(chunks, lengths)]
