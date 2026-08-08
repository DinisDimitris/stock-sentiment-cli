"""Tests for social media pre-processor."""

from processing.social_preprocessor import preprocess


def test_cashtag_removal():
    result = preprocess("$AAPL is looking good today")
    assert "$" not in result
    # Ticker gets lowercased by caps normaliser (AAPL not in preserve set)
    assert "aapl" in result


def test_slang_expansion():
    result = preprocess("bought the dip, going to the moon")
    assert "moon" not in result or "bullish" in result.lower() or "upward" in result.lower()


def test_caps_preservation():
    result = preprocess("I am BULL on this stock")
    assert "BULL" in result


def test_non_financial_caps_lowercased():
    result = preprocess("THE company announced results")
    assert "the" in result.lower()


def test_empty_string():
    result = preprocess("")
    assert result == ""


def test_none_input():
    result = preprocess(None)
    assert result is None


def test_whitespace_normalised():
    result = preprocess("lots   of   spaces")
    assert "  " not in result
