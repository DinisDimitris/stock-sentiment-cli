"""Tests for deduplicator content hashing and simhash."""

from deduplication.deduplicator import content_hash, compute_simhash, hamming_distance, normalise_text


def test_same_content_same_hash():
    h1 = content_hash("Apple Q3 Earnings", "Revenue beat estimates by 12%.")
    h2 = content_hash("Apple Q3 Earnings", "Revenue beat estimates by 12%.")
    assert h1 == h2


def test_different_content_different_hash():
    h1 = content_hash("Apple Q3 Earnings", "Revenue beat by 12%.")
    h2 = content_hash("Microsoft Q3 Earnings", "Revenue missed estimates.")
    assert h1 != h2


def test_normalisation_is_case_insensitive():
    h1 = content_hash("APPLE Q3 EARNINGS", "REVENUE BEAT BY 12%.")
    h2 = content_hash("apple q3 earnings", "revenue beat by 12%.")
    assert h1 == h2


def test_simhash_similar_texts_close():
    h1 = compute_simhash("Apple earnings beat revenue guidance", "Strong Q3 results reported")
    h2 = compute_simhash("Apple earnings beat revenue forecast", "Strong Q3 results reported today")
    # Very similar texts should have small Hamming distance — allow up to 15 bits
    dist = hamming_distance(h1, h2)
    assert dist <= 15


def test_simhash_different_texts_far():
    h1 = compute_simhash("Apple iPhone sales grew 15%", "Consumer demand remains robust")
    h2 = compute_simhash("Federal Reserve raises interest rates", "FOMC statement hawkish policy")
    dist = hamming_distance(h1, h2)
    assert dist > 5  # Very different texts should differ more


def test_hamming_distance_identical():
    assert hamming_distance(12345, 12345) == 0


def test_hamming_distance_one_bit():
    assert hamming_distance(0b1010, 0b1011) == 1


def test_simhash_value_fits_signed_64_bit_range():
    value = compute_simhash(
        "AAPL",
        "The quick brown fox jumps over the lazy dog " * 20,
    )

    assert -2**63 <= value <= 2**63 - 1
