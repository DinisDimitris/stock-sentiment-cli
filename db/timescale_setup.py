"""
TimescaleDB hypertable setup — run once at initialisation via cli.py db-init.
Hypertables and continuous aggregates cannot be created via Alembic migrations
because TimescaleDB DDL must be executed in a specific order and is not
reversible in the standard sense.
"""

import asyncpg


TIMESCALE_DDL = """
-- Enable extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- sentiment_scores is the primary time-series table.
-- Note: created here (not in Alembic) because it requires create_hypertable.
CREATE TABLE IF NOT EXISTS sentiment_scores (
    id              BIGSERIAL,
    document_id     BIGINT NOT NULL REFERENCES raw_documents(id),
    ticker          TEXT NOT NULL,
    model_used      TEXT NOT NULL,
    positive_prob   REAL NOT NULL,
    negative_prob   REAL NOT NULL,
    neutral_prob    REAL NOT NULL,
    raw_score       REAL NOT NULL,
    source_tier     INTEGER NOT NULL,
    source_weight   REAL NOT NULL,
    confidence_mult REAL NOT NULL DEFAULT 1.0,
    engagement_mult REAL NOT NULL DEFAULT 1.0,
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, scored_at)
);

SELECT create_hypertable('sentiment_scores', 'scored_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_sentiment_ticker_time
    ON sentiment_scores(ticker, scored_at DESC);

-- Continuous aggregate: pre-computed hourly weighted averages.
CREATE MATERIALIZED VIEW IF NOT EXISTS sentiment_hourly
WITH (timescaledb.continuous) AS
SELECT
    ticker,
    time_bucket('1 hour', scored_at) AS bucket,
    SUM(raw_score * source_weight * confidence_mult * engagement_mult)
        / NULLIF(SUM(source_weight * confidence_mult * engagement_mult), 0) AS weighted_avg,
    COUNT(*) AS document_count
FROM sentiment_scores
GROUP BY ticker, time_bucket('1 hour', scored_at)
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sentiment_hourly',
    start_offset => INTERVAL '30 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists => TRUE);

-- Compression: 95% space savings on data older than 7 days.
ALTER TABLE sentiment_scores SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker'
);

SELECT add_compression_policy('sentiment_scores', INTERVAL '7 days',
    if_not_exists => TRUE);

-- macro_indicators: FRED and Federal Reserve numeric time-series.
CREATE TABLE IF NOT EXISTS macro_indicators (
    id              BIGSERIAL,
    indicator_code  TEXT NOT NULL,
    indicator_name  TEXT NOT NULL,
    value           REAL NOT NULL,
    released_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id, released_at)
);

SELECT create_hypertable('macro_indicators', 'released_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_macro_code_time
    ON macro_indicators(indicator_code, released_at DESC);

-- Trigram index for fuzzy company name resolution
CREATE INDEX IF NOT EXISTS idx_aliases_trgm
    ON ticker_aliases USING gin(alias gin_trgm_ops);
"""


async def run_timescale_setup(db_url: str) -> None:
    """Execute all TimescaleDB DDL. Safe to run multiple times (uses IF NOT EXISTS)."""
    conn = await asyncpg.connect(dsn=db_url.replace("+asyncpg", ""))
    try:
        await conn.execute(TIMESCALE_DDL)
        print("[timescale] Hypertables and continuous aggregates initialised.")
    finally:
        await conn.close()
