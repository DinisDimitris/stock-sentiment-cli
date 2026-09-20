# Enhancement Backlog — Stock Sentiment CLI

Status: proposed
Scope: product and engineering enhancements derived from a read-through of the current
repository (`cli.py`, `agent/`, `ingestion/`, `output/`, `viewer/`, `api/`, `tests/`).

---

## 1. Project snapshot (what exists today)

The project is a local-first sentiment pipeline with a working end-to-end path:

```text
ingestion (SEC/IR/Finnhub/Reddit/StockTwits/Fed/FRED)
  -> dedup + FinBERT scoring
  -> PostgreSQL/TimescaleDB (raw_documents, sentiment_scores, events, analysis_runs)
  -> agent chain (conflict detection -> synthesis via OpenAI/Anthropic)
  -> delivery (rich terminal output, output/analysis/<TICKER>/{summary.txt,summary.json},
               FastAPI wrapper, static viewer, optional SMTP)
```

Concrete capabilities:

| Surface | Entry point | Notes |
| --- | --- | --- |
| CLI | `cli.py` (Click) | `db-init`, `add`, `remove`, `list`, `inspect`, `analyze`, `run` |
| Agent chain | `agent/review_agent.py` | 2-step LLM review, 6h cache in `analysis_runs` |
| Exports | `output/persistence.py` | `summary.txt` + `summary.json` per ticker |
| Viewer | `viewer/app.py` + `app.js` + `styles.css` | Reads export dir, renders one card per folder |
| API | `api/app.py` | `POST /analyze`, `GET /status/{ticker}` |
| Scheduling | `ingestion/scheduler.py` | fast/slow lanes, sequential analysis loop, SMTP digest |
| Tests | `tests/` | unit coverage for chunker, dedup, router, scorer, scheduler, CLI, exports |

Strengths worth protecting: the evidence trail is preserved, the pipeline is local-first and
inspectable, outputs are already dual (text + JSON), and the codebase is small enough to extend
without a framework rewrite.

---

## 2. Problem statement

**Primary problem.** Stock Sentiment can form an opinion about one ticker at a time, but it
cannot yet *present* that opinion legibly to a human, *compare* opinions across the watchlist,
or be *driven by an autonomous agent*. Three concrete consequences follow:

1. **The board buries signal under export artifacts.** Each card renders the raw contents of
   `summary.txt` as its summary paragraph, so every card repeats the same header
   (`Generated: ...`, `Source: GPT-4o-mini | ...`) and duplicates the direction/confidence that
   is already shown as a pill and in the metrics. The viewer has no search, filter, sort, or
   drill-down, so a watchlist of 8 tickers is already a scroll-and-squint exercise.
2. **There is no cross-ticker answer.** The only analysis entry point is
   `python cli.py analyze <one-company>` and the scheduler loops tickers sequentially. A user
   asking "what is the best stock to invest in, and which ones should I watch?" must run N
   commands, read N rich panels, and rank by hand. Nothing in the codebase computes, ranks, or
   justifies a "best / watch out for" list — even though `analysis_runs` already stores the
   scores needed to do it.
3. **No agent can reliably consume the output.** There is no machine-readable flag on
   `analyze` or `list`, failures still exit `0` (see `_analyze`, which prints and returns when a
   ticker cannot be resolved), and README line 3 advertises "add it as a plugin to your favourite
   harness" while no skill/plugin manifest, command contract, or guardrail documentation exists.
   An agent has no stable contract to call and no way to distinguish success from a fallback.

**Secondary problem.** The board treats export and failure artifacts as signal, which erodes
trust in the numbers it does show. In the checked-in `output/analysis/AAPL/summary.json`:

- the `summary` field is `"Agent analysis unavailable: Error code: 404 ..."`, yet it is rendered
  as a normal assessment with `direction: NEUTRAL` and `confidence_pct: 0`;
- `top_events` includes `10-Q: MAGELLAN PETROLEUM CORP` — evidence unrelated to Apple — so the
  ticker↔document association is over-broad;
- `output/formatter.py` hardcodes the label `GPT-4o-mini | fresh analysis` for *every* provider
  and model, and the terminal panel prints `Generated: <now>` instead of the stored
  `generated_at`, so the displayed provenance and timestamp can both be wrong.

**Per-epic problem statements** are included with each epic below.

---

## 3. Design principles for these changes

- **Additive and opt-in.** New CLI flags and endpoints default to current behavior; nothing that
  works today should break.
- **One source of truth per fact.** Structured data comes from `summary.json` / `analysis_runs`,
  not from parsing `summary.txt` prose.
- **Machine-readable first, pretty second.** Any data a skill depends on must be available as
  stable JSON with a documented schema.
- **Never present a failure as an opinion.** Errors are labeled as errors everywhere.
- **Testable without a database or an LLM.** New logic should be unit-testable with fixtures, in
  the style of the existing `tests/`.

---

## 4. Task index

| ID | Task | Epic | Priority |
| --- | --- | --- | --- |
| UX-1 | Render cards from structured JSON, not the raw text dump | Viewer UX | Now |
| UX-2 | Add search, filter, and sort to the board | Viewer UX | Now |
| UX-3 | Add a per-ticker detail view with deep links | Viewer UX | Next |
| UX-4 | Freshness, staleness, and data-quality badges | Viewer UX | Next |
| SKILL-1 | Machine-readable CLI contract (`--json`, exit codes, `--quiet`) | Agent skill | Now |
| SKILL-2 | `rank` command: best / watch / avoid across the watchlist | Agent skill | Now |
| SKILL-3 | Ship a `stocks-cli` agent skill (manifest + runbook) | Agent skill | Now |
| SKILL-4 | Batch and concurrent analysis (`analyze --all --concurrency`) | Agent skill | Next |
| TRUST-1 | Failure states are persisted and displayed as failures | Trust | Now |
| TRUST-2 | Evidence relevance: fix spurious ticker↔document links | Trust | Now |
| TRUST-3 | Correct model label and timestamp provenance | Trust | Next |
| INSIGHT-1 | `history` / `diff` command: what changed since yesterday | Insight | Next |
| INSIGHT-2 | Threshold alerts via webhook/ntfy/Discord | Insight | Later |
| OPS-1 | `doctor` command: one-shot environment health check | Ops | Next |
| OPS-2 | GitHub Actions CI for tests and lint | Ops | Next |
| OPS-3 | Viewer/API port conflict + docs and contract alignment | Ops | Now |

---

## 5. Epic 1 — Viewer UX (the "make the board readable" work)

### Epic problem statement

`viewer/app.js` builds each card's body from `stock.summary_text` (the literal contents of
`summary.txt`) and only falls back to `summary_json.summary` when the text is missing. Because
`summary.txt` begins with a file header, every card re-prints company/direction/confidence/date
and repeats a near-identical `Generated:` line. There is no way to find a ticker, hide a
direction, or order the grid, and there is no view that shows a single company's full evidence.

---

### UX-1 — Render cards from structured JSON, not the raw text dump

- **Priority:** Now
- **Problem:** The card `.summary` region contains `summary.txt` verbatim, including
  `Generated:`, `Source: GPT-4o-mini | ...`, and a duplicate direction/confidence line. The
  same lines appear on every card because all tickers are generated in the same run.
- **Feature:** Make `summary.json` the rendering contract. Show a short, purpose-built summary
  block: assessment text only, then drivers/risks/conflicts/events. Move provenance
  (`generated_at`, model, cache state) into a single card footer line or a tooltip, and drop the
  repeated per-card header entirely. When `summary_text` disagrees with `summary_json`, prefer
  JSON and render the text only inside a collapsed "raw export" disclosure.
- **Implementation sketch:**
  - `viewer/app.js`: replace the `stock.summary_text || data.summary` fallback in
    `createStockCard` with a `extractAssessment(stock)` helper that reads
    `data.summary`, and optionally strips a legacy header only as a compatibility shim.
  - Keep the existing `View summary.json` `<details>` as the escape hatch for raw text.
  - `viewer/app.py`: optionally add `summary_text_body` (header stripped) to each card so old
    exports also render cleanly, and stop shipping the full raw text as the primary field.
- **Acceptance criteria:**
  - No card displays a `Generated:` line inside its body.
  - Direction and confidence each appear exactly once per card.
  - A card built from the checked-in `output/analysis/*/summary.json` fixtures renders
    assessment + drivers + risks with no header artifacts.
  - `docs/ui-view.png` is regenerated after the change.

### UX-2 — Add search, filter, and sort to the board

- **Priority:** Now
- **Problem:** The grid is an unsorted, unfiltered `auto-fit` wall of cards. Finding one ticker
  means scanning, and there is no way to ask "show me only bearish names" or "sort by confidence".
- **Feature:** A control bar above the grid with: free-text search over ticker, company name, and
  sector; a direction filter (All / Bullish / Bearish / Mixed / Neutral); a sort selector
  (ticker, confidence, 7d score, last updated); and a result count. State persists in the URL
  query string so a filtered view is shareable and survives refresh.
- **Implementation sketch:**
  - `viewer/index.html`: add a `<section class="controls">` with an `<input type="search">`,
    two `<select>`s, and a reset button. Add `aria-label`s and a live region for the count.
  - `viewer/app.js`: introduce `state.filters`; add `applyFilters()` and `sortStocks()` before
    `render()`; wire `input`/`change` handlers to re-render; sync to `history.replaceState`.
  - `viewer/styles.css`: style the controls, focus rings, and an empty "no matches" state
    distinct from the existing "no folders found" state.
- **Acceptance criteria:**
  - Typing `nv` narrows the grid to matching tickers/companies as you type.
  - Selecting "Bearish" shows only bearish cards and updates the count.
  - Sorting by 7d score orders correctly with `N/A` values sorted last.
  - Reloading a URL with `?q=nv&direction=BULLISH` restores the same view.
  - Keyboard-only operation works (tab to controls, Escape clears search).

### UX-3 — Add a per-ticker detail view with deep links

- **Priority:** Next
- **Problem:** Everything a ticker has is crammed into one card, so the board is either too tall
  (show it all) or too shallow (truncate it). There is no URL for a single company.
- **Feature:** A detail view at `#/<TICKER>` (or `/ticker/<TICKER>`) showing the full assessment,
  all drivers/risks, every conflict with severity, the full event list, source breakdown by tier,
  macro overlay, and the raw JSON — while the board stays compact. Each card title links to it.
- **Implementation sketch:**
  - `viewer/app.py`: add `GET /api/stocks/<TICKER>` returning a single card, and have
    `get_stock_cards()` share a `build_card(folder)` helper to avoid duplication.
  - `viewer/app.js`: split `render()` from `renderDetail()`; use `hashchange` for routing so the
    existing static server needs no new path handling.
  - `viewer/styles.css`: add a `.detail` layout and a back link.
- **Acceptance criteria:**
  - Navigating to `#/AAPL` shows only Apple's detail; back returns to the board with filters intact.
  - Unknown tickers show a friendly not-found state, not a blank page.
  - The board card and the detail view read from the same `build_card` payload.

### UX-4 — Freshness, staleness, and data-quality badges

- **Priority:** Next
- **Problem:** `Updated` is the only time signal, and a card with a failed or empty analysis looks
  identical to a healthy one. Cards with no drivers/risks/events still render "No items available."
  three times, adding noise without information.
- **Feature:** A single status chip per card derived from the data: `Fresh` (< 6h), `Stale`
  (> 24h), `No data`, or `Failed` (see TRUST-1). Hide empty sections entirely and replace them
  with one compact "limited evidence" note. Surface document coverage (`document_count_7d`) as a
  low/medium/high evidence hint.
- **Implementation sketch:**
  - `viewer/app.js`: add `deriveStatus(stock)`; make `createListSection` return `null` for empty
    lists and filter nulls out of `sections.append(...)`.
  - `viewer/styles.css`: chip variants for fresh/stale/failed; a muted `.evidence-hint` style.
- **Acceptance criteria:**
  - A card updated 3 days ago shows `Stale`; one updated minutes ago shows `Fresh`.
  - Empty drivers/risks/events produce no "No items available." placeholders.
  - Low coverage (< 5 docs / 7d) is visibly flagged and does not look like a strong signal.

---

## 6. Epic 2 — Agent skill and cross-ticker ranking (the `/stocks-cli` work)

### Epic problem statement

The user-facing goal is a prompt such as:
`/stocks-cli what is the best stock to invest in and which ones to look out for in the future`,
after which an agent runs CLI commands to analyse each ticker and choose the best ones from
meaningful evidence. Today that is not possible: `analyze` emits rich terminal panels rather
than data, only handles one ticker, silently exits `0` on failure, and there is no ranked,
evidence-attached "best / watch" output. Nothing is packaged as a skill, despite the README
claiming plugin support.

---

### SKILL-1 — Machine-readable CLI contract (`--json`, exit codes, `--quiet`)

- **Priority:** Now
- **Problem:** An agent cannot parse Rich panels, and `analyze` returns exit code `0` even when
  resolution fails, so the agent cannot tell success from failure. There is no stable schema to
  depend on.
- **Feature:** A documented stdout contract for automation:
  - `python cli.py analyze <company> --json` prints exactly one JSON object (the same shape as
    `summary.json`) and nothing else to stdout; logs stay on stderr.
  - `python cli.py list --json` prints the watchlist as JSON.
  - `--quiet` suppresses Rich/progress output; `--fields` selects a subset for token economy.
  - Non-zero exit codes: `2` unresolved ticker, `3` database not initialized, `4` analysis
    failed, `5` no context/evidence.
  - `--schema` prints the JSON schema so an agent can validate its parse.
- **Implementation sketch:**
  - `cli.py`: add a `_emit(payload, as_json, quiet)` helper; thread `--json`/`--quiet` through
    `analyze` and `list`; raise `click.exceptions.Exit(code)` on the failure paths that
    currently `return` (e.g. `_analyze` unresolved branch, `_inspect_company_command`).
  - Add `--json` to `inspect` as an explicit alias of its current default, and switch its default
    to the human-readable form for consistency. (Breaking change — gate behind a minor version note.)
  - `docs/cli-contract.md`: publish the schemas, exit codes, and one worked example per command.
- **Acceptance criteria:**
  - `python cli.py analyze AAPL --json | jq .ticker` prints `"AAPL"` with zero non-JSON noise.
  - `python cli.py analyze NOT_A_TICKER --json; echo $?` prints `2`.
  - A failed LLM call exits `4`, and stdout still contains a well-formed JSON object with an
    error field (see TRUST-1) rather than a traceback.
  - Unit tests assert exit codes and that stdout parses with `json.loads`.

### SKILL-2 — `rank` command: best / watch / avoid across the watchlist

- **Priority:** Now
- **Problem:** There is no cross-ticker computation at all. "Best stock" and "ones to look out
  for" are answered by a human reading N separate panels, with no consistent criteria.
- **Feature:** `python cli.py rank` produces a ranked table (and `--json` a ranked array) over
  the watchlist using stored evidence, with an explicit, inspectable scoring formula rather than
  a black-box LLM judgment. Proposed composite per ticker:

  ```text
  opportunity = 0.45 * sentiment_7d + 0.25 * momentum(sentiment_7d - sentiment_30d)
              + 0.15 * confidence_pct/100 + 0.15 * evidence_coverage
  risk        = conflicts(HIGH) weight + abs(min(0, sentiment_1d)) + low-coverage penalty
  ```

  Output buckets: **Best candidates**, **Watch list** (improving but thin or conflicting
  evidence), **Avoid / deteriorating**. Every row carries the evidence that drove it: top
  driver, top risk, conflict count, coverage, and the `analysis_runs.run_id` used.
- **Implementation sketch:**
  - New `aggregation/ranking.py` with a pure `rank_tickers(rows, weights) -> list[RankedTicker]`
    function (unit-testable with fixtures, no DB), plus `score_to_bucket()`.
  - `cli.py`: new `rank` command; options `--json`, `--top N`, `--window 7d|30d`,
    `--min-coverage N`, `--explain` (prints the per-term contribution).
  - Data source: latest non-expired `analysis_runs` row per ticker, falling back to on-disk
    `summary.json` so the command works without a database.
  - `config/ranking_weights.yaml` so weights are tunable without code edits.
- **Acceptance criteria:**
  - `python cli.py rank --json` returns a ranked array with a `score`, `bucket`, `evidence`
    object, and `explain` breakdown per ticker.
  - Tickers with failed/thin analysis are bucketed `insufficient_evidence`, never `best`.
  - A fixture test with three known rows asserts a deterministic order and bucket assignment.
  - Weights are read from config and changing them changes the order in the test.

### SKILL-3 — Ship a `stocks-cli` agent skill (manifest + runbook)

- **Priority:** Now
- **Problem:** README advertises harness/plugin usage but no skill artifact exists, so
  `/stocks-cli ...` has nothing to invoke and an agent has no guardrails for a finance domain.
- **Feature:** A self-contained skill under `.agents/skills/stocks-cli/` (plus a copy/publish path
  for other harnesses) containing:
  - `SKILL.md` with frontmatter (`name: stocks-cli`, description, when-to-use) and an explicit
    decision procedure: refresh/analyse -> `rank --json` -> verify coverage -> select -> cite
    evidence.
  - `scripts/run.sh` (or `rank.py`) that wraps `python cli.py rank --json` and validates the
    schema, so the agent does not invent flags.
  - `references/cli-contract.md` (generated from SKILL-1) and `references/scoring.md`.
  - Guardrails: never present output as financial advice; require `--min-coverage`; require a
    `--fresh` analysis when the newest run is older than a threshold; surface "insufficient
    evidence" instead of guessing; always attach driver/risk citations and `run_id`s.
  - Graceful degradation when no LLM key or DB is present (report the blocker, do not fabricate).
- **Implementation sketch:**
  - New directory `.agents/skills/stocks-cli/`; add a `make skill-install` target or
    `python cli.py install-skill --target <harness-dir>` helper that symlinks/copies the skill.
  - `README.md`: replace the vague "add it as a plugin" line with a real "Use as an agent skill"
    section showing the `/stocks-cli ...` prompt and the exact commands the skill runs.
- **Acceptance criteria:**
  - `/stocks-cli what is the best stock to invest in and which ones to look out for in the future`
    completes end to end on a seeded workspace and returns: a ranked shortlist, the evidence for
    each pick, explicit watch-list candidates, and a "not enough evidence" list.
  - The skill never calls an undocumented flag and never emits a recommendation without at least
    one cited driver or event per pick.
  - Running the skill with no LLM key produces a clear blocker message, not a fabricated answer.
  - A test invokes `scripts/run.sh` against a fixture export dir and asserts schema-valid output.

### SKILL-4 — Batch and concurrent analysis (`analyze --all --concurrency`)

- **Priority:** Next
- **Problem:** `analyze` is single-ticker and `_run_analysis_cycle` loops sequentially
  (`for ticker in tickers`), so a watchlist-sized ranking refresh is slow and the skill may exceed
  an agent's time budget.
- **Feature:** `python cli.py analyze --all` with a bounded `--concurrency` (default 4) and
  `--since`/`--stale-only` selection, reusing the existing cache unless `--fresh`. Emits a JSON
  summary of per-ticker outcomes and a non-zero exit if any ticker failed.
- **Implementation sketch:**
  - `cli.py`: extend `analyze` with `--all`, `--concurrency`, `--stale-only`, `--fresh`.
  - Factor the per-ticker body of `_analyze` into `_analyze_one(ticker, force_refresh)`; drive it
    with `asyncio.Semaphore` + `asyncio.gather`.
  - Reuse the function in `ingestion/scheduler._run_analysis_cycle` to remove the sequential loop.
- **Acceptance criteria:**
  - `analyze --all --concurrency 4` processes a 4-ticker fixture with at most 4 concurrent calls.
  - A single ticker failure does not abort the batch; it appears in the JSON summary with its
    error and exit code.
  - The scheduler produces byte-identical exports for the same inputs as before the refactor.

---

## 7. Epic 3 — Trust and data quality

### Epic problem statement

The board and the exports currently present artifacts as if they were analysis. A failed LLM
call is stored and rendered as a `NEUTRAL / 0%` assessment; unrelated SEC filings appear under a
ticker's top events; and the provenance label is hardcoded. Each of these makes the system look
worse than it is, and an agent skill built on top would amplify the errors.

---

### TRUST-1 — Failure states are persisted and displayed as failures

- **Priority:** Now
- **Problem:** `run_review` returns a dict whose `summary` is
  `"Agent analysis unavailable: ..."`, and `_store_result` is skipped, but
  `write_analysis_output` still writes that string to `summary.txt`/`summary.json`. The viewer
  renders it as a normal assessment. There is no `status` or `error` column on `analysis_runs`.
- **Feature:** First-class run status. `analysis_runs` gains `status` (`ok|failed|partial`) and
  `error_message`; the export gains `status` and `error`. Persist failed runs (so history and
  ranking can exclude them) instead of dropping them. Every surface renders a failed run as a
  failure and never as an opinion.
- **Implementation sketch:**
  - `alembic/versions/0003_add_analysis_run_status.py`: add the two columns with a default of
    `ok` for existing rows.
  - `agent/review_agent.py`: set `status`/`error` on the result; stop skipping `_store_result`;
    keep the existing warning log.
  - `output/persistence.py` / `output/formatter.py`: write and render the status.
  - `viewer/app.js`: use the status to show the `Failed` chip from UX-4 and suppress the
    assessment block.
- **Acceptance criteria:**
  - After a simulated LLM exception, `summary.json` has `"status": "failed"` and a non-empty
    `error`, the viewer shows a `Failed` badge, and `rank` excludes the ticker from `best`.
  - A migration test upgrades and downgrades cleanly.
  - Successful runs keep `"status": "ok"` and render exactly as before.

### TRUST-2 — Evidence relevance: fix spurious ticker↔document links

- **Priority:** Now
- **Problem:** `ingestion/sources/sec_edgar.py` builds its query from a bare ticker full-text
  search (`"q": f'"{ticker}"'`), and `ingestion/base_source.py` links every fetched document to
  the requested ticker. The checked-in `output/analysis/AAPL/summary.json` consequently lists
  `10-Q: MAGELLAN PETROLEUM CORP` among Apple's top events, inflating apparent coverage with
  irrelevant documents.
- **Feature:** A relevance gate before a document is linked to a ticker, plus an auditable score.
  Requirements: prefer CIK-based EDGAR lookups over full-text ticker search; require a
  company-name/CIK match for filings; keep a configurable confidence on `DocumentCompany`;
  and add a `--min-relevance` filter used by scoring, context building, and `inspect`.
- **Implementation sketch:**
  - `ingestion/sources/sec_edgar.py`: resolve the ticker to a CIK (reuse the existing EDGAR
    resolution path in `resolution/ticker_resolver.py`) and query by CIK.
  - `ingestion/base_source.py`: compute a relevance score (entity/CIK match > title match >
    body mention) and set `DocumentCompany.confidence`; skip below-threshold links.
  - `aggregation/scorer.py` / `agent/context_builder.py`: filter events and documents by
    `dc.confidence >= min_relevance`.
  - Emit a one-line audit log per skipped link.
- **Acceptance criteria:**
  - Ingesting for `AAPL` no longer links the Magellan Petroleum 10-Q to Apple (fixture replay
    test using the stored `raw_json`).
  - `python cli.py inspect AAPL --json` includes only documents whose relevance meets the default
    threshold, and the count matches `document_count_7d`.
  - A migration-free config knob controls the threshold, with a documented default.

### TRUST-3 — Correct model label and timestamp provenance

- **Priority:** Next
- **Problem:** `output/formatter.py::settings_model_label` hardcodes `GPT-4o-mini` for Anthropic
  runs and for any other model, and `render_summary` prints `Generated: <now>` (from
  `datetime.now`) instead of the stored `generated_at`, contradicting `format_summary_text`.
- **Feature:** Store the provider and model actually used on the result
  (`llm_provider`, `llm_model`), and render provenance from stored values everywhere:
  `render_summary` shows `generated_at`; `settings_model_label` reports the real model and cache
  state. Include both fields in `summary.json` and on the viewer card footer.
- **Implementation sketch:**
  - `agent/review_agent.py`: capture `get_provider()`/model per step and add to `result`.
  - `output/formatter.py`: replace the hardcoded string; fix the `now_str` usage.
  - `viewer/app.js`: render `data.llm_model` in the footer.
- **Acceptance criteria:**
  - An Anthropic-backed run reports `claude-*`, not `GPT-4o-mini`, in both terminal and file output.
  - The terminal panel's `Generated:` equals `summary.json.generated_at`.
  - A fixture test covers both providers.

---

## 8. Epic 4 — Insight, history, and alerts

### Epic problem statement

The README promises answers to "What changed around this company in the last 24 hours?", but
`analysis_runs` history is write-only: nothing computes deltas or surfaces what is new. Alerts
are computed (`viral_alert`) and then ignored outside the CLI panel, so the product cannot push
a signal; a user must poll.

### INSIGHT-1 — `history` / `diff` command: what changed since yesterday

- **Priority:** Next
- **Problem:** Every run overwrites `summary.json`, so previous assessments are only recoverable
  from the `analysis_runs` table, and no command reads them back.
- **Feature:** `python cli.py history <company> [--days 7]` lists recent runs
  (direction, confidence, scores, status, timestamp) and
  `python cli.py diff <company> [--since 1d]` reports deltas: direction change, confidence
  change, score deltas, newly added drivers/risks/conflicts, and new events since the previous
  run. Both support `--json` for the skill.
- **Implementation sketch:**
  - New `output/history.py` with pure diff helpers over two result dicts
    (`diff_results(previous, current) -> dict`), unit-tested with fixtures.
  - `cli.py`: `history` and `diff` commands reading `analysis_runs`, with a file-based fallback.
- **Acceptance criteria:**
  - `history AAPL --json` returns runs newest-first with status and scores.
  - `diff AAPL --since 1d` correctly reports a direction flip and added drivers in a fixture test.
  - A ticker with only one run returns a clear "no previous run to compare" message and exit `0`.

### INSIGHT-2 — Threshold alerts via webhook/ntfy/Discord

- **Priority:** Later
- **Problem:** `viral_alert` and high-severity conflicts are computed but only appear when a
  human opens the terminal or the board; there is no push channel.
- **Feature:** A pluggable notifier fired at the end of an analysis cycle when configurable
  conditions are met (direction flip, HIGH conflict appears, `viral_alert` true, confidence
  crosses a threshold, coverage falls below a floor). Ship a generic JSON webhook and an `ntfy`
  adapter; keep SMTP as-is.
- **Implementation sketch:**
  - New `output/notifiers.py` with a `Notifier` protocol and `WebhookNotifier`/`NtfyNotifier`.
  - `ingestion/scheduler.py`: after `_run_analysis_cycle`, evaluate a small rule set from
    `config/alert_rules.yaml` and dispatch.
  - `.env.example`: `ALERT_WEBHOOK_URL`, `NTFY_TOPIC`, `ALERT_MIN_SEVERITY`.
- **Acceptance criteria:**
  - With a local stub server, a direction flip produces exactly one webhook POST containing the
    ticker, change, and evidence.
  - No alert fires when conditions are not met, and failures to notify never break the cycle.
  - Rule configuration is documented and covered by a unit test.

---

## 9. Epic 5 — Operations and quality gates

### Epic problem statement

There is no CI, no single "is my install healthy?" command, no tests for `viewer/`, and the
documented ports disagree: `viewer/app.py` defaults to `8000` while the README also tells users
to run `uvicorn` (also `8000`) and then open `127.0.0.1:8000` for the viewer.

### OPS-1 — `doctor` command: one-shot environment health check

- **Priority:** Next
- **Problem:** Diagnosing a broken install requires running several commands and reading logs;
  `load_models()` health output only appears during `run`.
- **Feature:** `python cli.py doctor` checks and reports, with pass/fail per item and a non-zero
  exit on hard failures: DB reachability and migrations applied, required tables present, LLM
  provider/key resolution, FinBERT model availability and device, `ANALYSIS_OUTPUT_DIR`
  writability, watchlist size and backfill status, and export freshness per ticker. `--json` for
  automation and the skill.
- **Implementation sketch:**
  - New `ops/doctor.py` exporting `run_checks() -> list[CheckResult]` (pure where possible).
  - `cli.py`: `doctor` command rendering a table via `rich`.
  - Reuse `_ensure_db_ready`, `processing.model_registry.load_models`, `agent.llm_client.get_provider`.
- **Acceptance criteria:**
  - Missing `OPENAI_API_KEY` + `ANTHROPIC_API_KEY` reports FAIL with the exact remediation command.
  - Unreachable DB reports FAIL without a traceback and exits non-zero.
  - `doctor --json` is schema-valid and covered by a test with mocked checks.

### OPS-2 — GitHub Actions CI for tests and lint

- **Priority:** Next
- **Problem:** There is no `.github/workflows`, so regressions in `cli.py`, `agent/`, and the
  viewer are only caught locally; the repo is advertised as open-source-ready.
- **Feature:** CI on push/PR that installs dependencies, runs `python -m pytest -q`, and runs a
  linter/formatter check. Keep ML-heavy tests skipped or mocked so CI stays fast and does not
  download FinBERT.
- **Implementation sketch:**
  - `.github/workflows/ci.yml` with a Python matrix (3.11, 3.12), `pip install -r requirements.txt`,
    `pytest -q`, and `ruff check .`.
  - Add `ruff` to `requirements.txt` (dev section) and a minimal `pyproject.toml`/`ruff.toml`.
  - Mark model-download tests with a `requires_models` marker, deselected by default in CI.
- **Acceptance criteria:**
  - A PR with a deliberately broken test shows a red check.
  - The full CI run completes in a few minutes without downloading model weights.
  - `ruff check` passes on the current tree (or the baseline violations are explicitly ignored).

### OPS-3 — Viewer/API port conflict + docs and contract alignment

- **Priority:** Now
- **Problem:** `VIEWER_PORT` defaults to `8000` in `viewer/app.py`, the same default as
  `uvicorn api.app:app`, and the README tells users to open `127.0.0.1:8000` for the viewer.
  Separately, `.env.example` documents `ANALYSIS_DIR=output/analysis` as a relative path while
  `viewer/app.py` resolves it against the process CWD, so running the viewer from another
  directory silently reads nothing.
- **Feature:** Make the viewer default to a non-conflicting port (e.g. `8010`, matching the
  Traefik example) and resolve `ANALYSIS_DIR` relative to the repository root when it is not
  absolute. Update README, `docs/deployment.md`, and `.env.example` to state the real ports, and
  add a docs-consistency test that the documented default equals the code default.
- **Implementation sketch:**
  - `viewer/app.py`: default `VIEWER_PORT` to `8010`; resolve relative `ANALYSIS_DIR` against
    `ROOT.parent`.
  - `README.md`, `docs/deployment.md`, `.env.example`, `viewer/docker-compose.traefik.example.yml`:
    align ports and paths.
  - `tests/test_viewer.py`: assert the resolved default path and that a relative override resolves
    against the repo root; add tests for `get_stock_cards` against a `tmp_path` fixture, including
    a malformed `summary.json` and an empty directory.
- **Acceptance criteria:**
  - Starting the viewer and the API together with defaults binds two different ports.
  - Running `python viewer/app.py` from a different CWD still finds `output/analysis`.
  - `pytest` covers `get_stock_cards` (happy path, malformed JSON, empty dir) and the path
    resolution.
  - `grep`-based doc test fails if a documented default diverges from the code.

---

## 10. Suggested sequencing

**Milestone 1 — "Trustworthy board" (Now):** UX-1, UX-2, UX-4 (partial), TRUST-1, TRUST-2,
OPS-3. Result: the viewer shows only real signal, the numbers are trustworthy, and default
setup no longer collides.

**Milestone 2 — "Agent-ready" (Now → Next):** SKILL-1, SKILL-2, SKILL-3, TRUST-3, OPS-2.
Result: `/stocks-cli ...` works end to end with a machine-readable contract, a defensible
ranking, and CI protecting it.

**Milestone 3 — "Deeper insight" (Next):** UX-3, SKILL-4, INSIGHT-1, OPS-1. Result: drill-down
plus history/diff and a health command.

**Milestone 4 — "Proactive" (Later):** INSIGHT-2 and any ranking-weight tuning driven by
observed precision.

---

## 11. Non-goals

- No real-money trading, order placement, or brokerage integration.
- No replacement of FinBERT with a hosted sentiment API.
- No multi-tenant auth, user accounts, or hosted SaaS concerns (this is local-first).
- No change to the existing provider set (OpenAI/Anthropic) in this backlog.
