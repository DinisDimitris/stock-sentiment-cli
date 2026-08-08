"""Tests for text chunker."""

from processing.chunker import chunk_text, chunk_and_weight


def test_short_text_returns_single_chunk():
    text = "Apple reported strong quarterly earnings."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_long_text_produces_multiple_chunks():
    # Generate a text that's clearly over 400 tokens
    sentence = "The company reported strong earnings growth driven by product innovation. "
    text = sentence * 60  # ~60 * 12 tokens ≈ 720 tokens
    chunks = chunk_text(text)
    assert len(chunks) > 1


def test_chunk_weights_sum_to_one():
    sentence = "Quarterly earnings exceeded analyst expectations significantly. "
    text = sentence * 60
    weighted = chunk_and_weight(text)
    total = sum(w for _, w in weighted)
    assert abs(total - 1.0) < 0.01


def test_empty_text():
    assert chunk_text("") == []


def test_chunk_and_weight_short():
    text = "Short text."
    weighted = chunk_and_weight(text)
    assert len(weighted) == 1
    assert abs(weighted[0][1] - 1.0) < 0.001
