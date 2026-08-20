# Architecture

Stock Sentiment is a local-first pipeline that moves data through five stages:

1. Ingestion
2. Processing
3. Persistence
4. Synthesis
5. Delivery

## End-to-end flow

```text
Source adapters -> task queue -> preprocessing/chunking/dedup -> FinBERT scoring
-> context builder -> LLM synthesis -> terminal/API/viewer/email/file exports
```

## 1. Ingestion

The ingestion layer lives in `ingestion/` and is coordinated by `ingestion/scheduler.py`.

Primary source families:

- SEC EDGAR for filings and fast-lane company updates
- Company investor-relations feeds
- Finnhub news and transcripts
- Reddit communities
- StockTwits social chatter
- Federal Reserve speeches and releases
- FRED macro indicators

The scheduler runs two operational lanes:

- Fast lane for CRITICAL tasks that should be processed quickly
- Slow lane for the broader background queue

The default worker shape is:

- 2 fast workers
- 4 slow workers

That split keeps urgent company updates from waiting behind slower background ingestion.

## 2. Processing

The processing layer lives mainly in `processing/` and `deduplication/`.

Key responsibilities:

- social-text cleanup and normalization
- chunking long source documents into model-sized pieces
- routing content to the right scoring path
- deduplicating near-identical documents with SimHash
- scoring text through several FinBERT-family models

`processing/model_registry.py` loads the local models once at startup. The runtime can use:

- `FINBERT_DEVICE=auto`
- `FINBERT_DEVICE=cpu`
- `FINBERT_DEVICE=cuda`

In `auto`, the registry checks whether the installed Torch build can actually serve the local GPU and falls back to CPU if not.

## 3. Persistence

The project stores state in PostgreSQL/TimescaleDB.

Main database responsibilities:

- watched companies and metadata
- ticker aliases and resolution data
- raw ingested documents
- queued processing tasks
- cached analysis runs

`cli.py db-init` is the canonical bootstrap path. It:

- runs Alembic migrations
- applies TimescaleDB setup helpers
- seeds source-tier configuration

## 4. Synthesis

The synthesis layer lives in `agent/`.

The flow is intentionally staged:

1. Build a structured context packet for a ticker
2. Ask the LLM to identify conflicts and contradictions
3. Ask the LLM to synthesize direction, confidence, drivers, and risks
4. Cache the result for `AGENT_CACHE_TTL` seconds

Supported LLM providers:

- OpenAI
- Anthropic

Provider selection is controlled by `LLM_PROVIDER`.

If `LLM_PROVIDER=auto`, the app uses the first configured key in this order:

1. `OPENAI_API_KEY`
2. `ANTHROPIC_API_KEY`

Each provider has default and escalation models so the synthesis step can use a larger model when the context looks more conflicted.

## 5. Delivery

The final result can be consumed several ways.

### CLI

`python cli.py analyze <ticker>` renders a formatted terminal summary.

### File exports

`output/persistence.py` writes:

- `summary.txt`
- `summary.json`

under `ANALYSIS_OUTPUT_DIR/<ticker>/`.

### API

`api/app.py` exposes a minimal FastAPI surface for remote requests.

### Viewer

`viewer/app.py` reads the exported analysis bundles from disk and serves a browser view.

### Email

If SMTP is configured, scheduled runs can send summary emails after analysis completes.

## Configuration files worth knowing

- `config/source_tiers.yaml` controls relative source trust/weighting
- `config/sector_macro_weights.yaml` controls how macro indicators affect sectors
- `.env.example` documents the supported runtime variables
- `ops/systemd/` contains user-service templates for Linux deployments

## Practical mental model

A good way to think about the project is:

- the ingestion layer gathers evidence
- the processing layer cleans and scores evidence
- the database preserves evidence and queue state
- the agent layer turns evidence into a usable opinion
- the delivery layer decides where that opinion goes
