# stock-sentiment

Stock Sentiment is a Python pipeline for collecting financial and social signals, processing them into normalized documents, and generating sentiment-aware summaries for watched companies.

The project combines:
- ingestion adapters for SEC filings, earnings materials, news, Reddit, social platforms, and macro data,
- a processing pipeline for preprocessing, chunking, deduplication, and scoring,
- a CLI for managing a watchlist and kicking off ingestion/anomaly analysis,
- an optional API layer for serving results.

## Project layout

- `cli.py` – main command-line interface
- `ingestion/` – source adapters and scheduling
- `processing/` – text preprocessing, chunking, routing, and worker execution
- `aggregation/` – scoring and macro overlay logic
- `db/` – SQLAlchemy models and database helpers
- `agent/` – review-agent orchestration and prompt templates
- `output/` – rendering for analysis summaries
- `tests/` – pytest coverage for the core pipeline components

## Prerequisites

- Python 3.11+
- Docker Desktop (recommended for running the local TimescaleDB instance)
- Optional API keys for Finnhub, GitHub Models/OpenAI-compatible endpoints, Reddit, and FRED

## Quick start

1. Create and activate a virtual environment.
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies.
   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example environment file and fill in the values you want to use.
   ```bash
   cp .env.example .env
   ```

4. Start the local database.
   ```bash
   docker compose up -d db
   ```

5. Initialize the database and seed the source-tier configuration.
   ```bash
   python cli.py db-init
   ```

6. Add a company to the watchlist.
   ```bash
   python cli.py add "Apple"
   ```

7. Run the ingestion workflow.
   ```bash
   python cli.py run --interval weekly
   ```

8. Review the analysis for a company.
   ```bash
   python cli.py analyze "Apple"
   ```

## Configuration

The application reads configuration from `.env` (via `pydantic-settings`). The key values are:

- `DB_URL` / `DB_URL_SYNC` – PostgreSQL connection string for the main database
- `GITHUB_PAT` – GitHub Models access token (used by the agent layer)
- `FINNHUB_KEY` – Finnhub API key for company metadata and news lookups
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` – Reddit API credentials
- `FRED_API_KEY` – API key for FRED indicator ingestion
- `FMP_API_KEY` – optional fallback for earnings transcript sources

You can inspect the defaults in `.env.example`.

## CLI reference

Run the CLI with:

```bash
python cli.py --help
```

### `db-init`

Initializes the entire local database setup.

What it does:
- runs Alembic migrations (`alembic upgrade head`),
- creates the TimescaleDB hypertables / setup objects,
- seeds the source-tier configuration from `config/source_tiers.yaml`.

Example:
```bash
python cli.py db-init
```

### `add <company>`

Adds a company to the watchlist.

Behavior:
- accepts either a company name or a ticker,
- resolves the symbol using the ticker resolver,
- inserts the company into the database,
- queues a backfill task so the next ingestion cycle will gather historical data.

Examples:
```bash
python cli.py add "Apple"
python cli.py add AAPL
```

### `remove <ticker>`

Removes a company from the watchlist.

Example:
```bash
python cli.py remove AAPL
```

### `list`

Lists the currently watched companies and their backfill state.

Example:
```bash
python cli.py list
```

### `analyze <company>`

Runs the sentiment-analysis workflow for a company and prints the generated investment summary.

Options:
- `--fresh` – bypasses the 6-hour analysis cache and forces a fresh review.

Examples:
```bash
python cli.py analyze "Apple"
python cli.py analyze AAPL --fresh
```

### `run`

Starts the ingestion and processing workflow.

Options:
- `--once` – run a single ingestion cycle and exit instead of staying resident.
- `--interval <value>` – schedule the daemon to repeat the ingestion cycle on a fixed cadence. Supported values include:
  - numeric intervals such as `15m`, `1h`, `2h`, `2d`, `2w`
  - named values such as `hourly`, `daily`, `weekly`, `biweekly`
  - human-readable phrases such as `2 weeks`
- `--log-file <path>` – write logs to a file in addition to standard error.

Examples:
```bash
python cli.py run --once
python cli.py run --interval 15m
python cli.py run --interval 1h
python cli.py run --interval daily
python cli.py run --interval weekly
python cli.py run --interval "2 weeks"
python cli.py run --once --log-file ./stock-sentiment.log
```

## Development and testing

Run the test suite with:

```bash
pytest -q
```

If you want to run the API locally, use:

```bash
uvicorn api.app:app --reload
```

## Notes

- The ingestion daemon only processes companies that have been added to the watchlist.
- If no API keys are configured, the pipeline will still start, but some data sources may skip ingestion or return partial results.
- `db-init` will fail fast if Alembic migrations do not complete successfully.
