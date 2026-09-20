/**
 * Unit tests for the viewer's pure view logic.
 *
 * Run with: node --test viewer/
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const app = require("./app.js");

function makeStock(overrides) {
  const stock = {
    ticker: "AAPL",
    status: "fresh",
    last_updated: "2026-09-13T09:00:00+00:00",
    coverage: { level: "high", document_count_7d: 120 },
    summary_json: {
      company_name: "Apple Inc",
      sector: "Technology",
      direction: "BULLISH",
      confidence_pct: 75,
      summary: "Services momentum offsets hardware softness.",
      primary_drivers: ["Services growth"],
      primary_risks: ["China exposure"],
      conflicts: [],
      top_events: [],
      composite_score_1d: 0.2,
      composite_score_7d: 0.42,
      composite_score_30d: 0.31,
      document_count_7d: 120,
      trend: "improving",
    },
  };
  return Object.assign({}, stock, overrides, {
    summary_json: Object.assign({}, stock.summary_json, overrides && overrides.summary_json),
  });
}

// --- UX-2: search, filter, sort ---------------------------------------------

test("search matches ticker, company, and sector", () => {
  const stocks = [
    makeStock({ ticker: "NVDA", summary_json: { company_name: "NVIDIA Corp", sector: "Technology" } }),
    makeStock({ ticker: "MSFT", summary_json: { company_name: "Microsoft Corp", sector: "Technology" } }),
    makeStock({ ticker: "GRMN", summary_json: { company_name: "Garmin Ltd", sector: "Consumer products" } }),
  ];

  const byTicker = app.applyFilters(stocks, { q: "nv", direction: "ALL" });
  assert.deepEqual(byTicker.map((s) => s.ticker), ["NVDA"]);

  const byCompany = app.applyFilters(stocks, { q: "garmin", direction: "ALL" });
  assert.deepEqual(byCompany.map((s) => s.ticker), ["GRMN"]);

  const bySector = app.applyFilters(stocks, { q: "consumer", direction: "ALL" });
  assert.deepEqual(bySector.map((s) => s.ticker), ["GRMN"]);
});

test("direction filter keeps only bearish cards", () => {
  const stocks = [
    makeStock({ ticker: "AAA", summary_json: { direction: "BEARISH" } }),
    makeStock({ ticker: "BBB", summary_json: { direction: "BULLISH" } }),
    makeStock({ ticker: "CCC", summary_json: { direction: "BEARISH" } }),
  ];

  const filtered = app.applyFilters(stocks, { q: "", direction: "BEARISH" });
  assert.deepEqual(filtered.map((s) => s.ticker), ["AAA", "CCC"]);
});

test("sort by 7d score orders descending with N/A last", () => {
  const stocks = [
    makeStock({ ticker: "NULL", summary_json: { composite_score_7d: null } }),
    makeStock({ ticker: "LOW", summary_json: { composite_score_7d: -0.2 } }),
    makeStock({ ticker: "HIGH", summary_json: { composite_score_7d: 0.9 } }),
    makeStock({ ticker: "MISSING" }),
  ];
  stocks[3].summary_json = Object.assign({}, stocks[3].summary_json);
  delete stocks[3].summary_json.composite_score_7d;

  const sorted = app.sortStocks(stocks, "score_7d");
  const order = sorted.map((s) => s.ticker);
  // Numeric scores come first, descending; the two N/A entries fall to the end
  // and are ordered deterministically by ticker.
  assert.deepEqual(order.slice(0, 2), ["HIGH", "LOW"]);
  assert.deepEqual(order.slice(2).sort(), ["MISSING", "NULL"]);
});

test("sort by confidence puts unknown values last", () => {
  const stocks = [
    makeStock({ ticker: "A", summary_json: { confidence_pct: 40 } }),
    makeStock({ ticker: "B", summary_json: { confidence_pct: 90 } }),
    makeStock({ ticker: "C", summary_json: { confidence_pct: null } }),
  ];

  assert.deepEqual(app.sortStocks(stocks, "confidence").map((s) => s.ticker), ["B", "A", "C"]);
});

test("sort by ticker is alphabetical", () => {
  const stocks = [makeStock({ ticker: "MSFT" }), makeStock({ ticker: "AAPL" }), makeStock({ ticker: "NVDA" })];
  assert.deepEqual(app.sortStocks(stocks, "ticker").map((s) => s.ticker), ["AAPL", "MSFT", "NVDA"]);
});

test("count label reads naturally", () => {
  assert.equal(app.countLabel(8, 8), "8 tickers");
  assert.equal(app.countLabel(1, 8), "1 of 8 tickers");
  assert.equal(app.countLabel(1, 1), "1 ticker");
  assert.equal(app.countLabel(0, 0), "0 tickers");
});

// --- UX-1: card body comes from structured JSON ------------------------------

test("card contains no generated header and shows direction/confidence once", () => {
  const html = app.buildCardHtml(makeStock());

  assert.equal(html.includes("Generated:"), false);
  assert.equal(html.includes("Direction:"), false);
  assert.equal((html.match(/BULLISH/g) || []).length, 1);
  assert.equal((html.match(/Confidence/g) || []).length, 1);
  assert.equal(html.includes("Services momentum offsets hardware softness."), true);
  assert.equal(html.includes("Services growth"), true);
  assert.equal(html.includes("China exposure"), true);
});

test("card links to the detail view for the ticker", () => {
  assert.equal(app.buildCardHtml(makeStock()).includes("#/AAPL"), true);
});

test("legacy header text is never used when JSON is present", () => {
  const stock = makeStock({
    summary_text: "AAPL (Apple Inc) | Technology\nDirection: BULLISH | Confidence: 75%\nGenerated: yesterday\n\nAssessment:\nOld text",
  });

  const html = app.buildCardHtml(stock);
  assert.equal(html.includes("Generated:"), false);
  assert.equal(html.includes("Old text"), false);
});

// --- UX-4: status and coverage badges ---------------------------------------

test("stale and fresh statuses produce their own chips", () => {
  assert.equal(app.buildCardHtml(makeStock({ status: "stale" })).includes("status-chip--stale"), true);
  assert.equal(app.buildCardHtml(makeStock({ status: "fresh" })).includes("status-chip--fresh"), true);
  assert.equal(app.buildCardHtml(makeStock({ status: "no_data" })).includes("status-chip--no_data"), true);
});

test("low coverage is visibly flagged", () => {
  const html = app.buildCardHtml(makeStock({ coverage: { level: "low", document_count_7d: 2 } }));
  assert.equal(html.includes("Low evidence"), true);
  assert.equal(html.includes("evidence-hint--low"), true);
});

test("empty sections produce no placeholder noise", () => {
  const stock = makeStock({
    summary_json: { primary_drivers: [], primary_risks: [], conflicts: [], top_events: [] },
  });

  const html = app.buildCardHtml(stock);
  assert.equal(html.includes("No items available."), false);
  assert.equal(html.includes("No conflicts reported."), false);
  assert.equal(html.includes("Limited evidence"), true);
});

test("a failed run shows an error block and no sentiment pill", () => {
  const html = app.buildCardHtml(
    makeStock({
      status: "failed",
      error_message: "provider 404",
      summary_json: { direction: "NEUTRAL", confidence_pct: 0 },
    })
  );

  assert.equal(html.includes("status-chip--failed"), true);
  assert.equal(html.includes("provider 404"), true);
  assert.equal(html.includes("sentiment-pill"), false);
});

// --- UX-3: detail view -------------------------------------------------------

test("detail view renders tier breakdown, macro overlay, and every event", () => {
  const events = [1, 2, 3, 4, 5, 6].map((n) => ({
    headline: "Event " + n,
    date: "2026-09-0" + n,
    importance: "HIGH",
    type: "news",
    score: 0.1 * n,
  }));
  const stock = makeStock({
    summary_text: "AAPL (Apple Inc) | Technology\nGenerated: 2026-09-13\n\nAssessment:\nA body",
    summary_json: {
      top_events: events,
      source_breakdown: { tier_1: { score: 0.4, count: 3 }, tier_3: { score: -0.1, count: 8 } },
      macro_overlay: { score: 0.1, description: "Neutral", dominant_factor: "rates" },
    },
  });

  const html = app.buildDetailHtml(stock);
  assert.equal(html.includes("Source breakdown"), true);
  assert.equal(html.includes("Tier 1 — SEC filings"), true);
  assert.equal(html.includes("Macro overlay"), true);
  assert.equal(html.includes("Event 6"), true);
  assert.equal(html.includes("summary.txt"), true);
  assert.equal(html.includes("Back to board"), true);
});

test("board card stays compact by capping events", () => {
  const events = [1, 2, 3, 4, 5].map((n) => ({ headline: "Event " + n, date: "2026-09-01" }));
  const html = app.buildCardHtml(makeStock({ summary_json: { top_events: events } }));

  assert.equal(html.includes("Event 3"), true);
  assert.equal(html.includes("Event 4"), false);
});

test("not-found view names the ticker", () => {
  const html = app.buildNotFoundHtml("ZZZZ");
  assert.equal(html.includes("ZZZZ not found"), true);
});

// --- UX-2: URL state ---------------------------------------------------------

test("URL query restores search, direction, and sort", () => {
  assert.deepEqual(app.parseFilters("?q=nv&direction=BULLISH"), {
    q: "nv",
    direction: "BULLISH",
    sort: "ticker",
  });
  assert.deepEqual(app.parseFilters("?q=nv&direction=BEARISH&sort=score_7d"), {
    q: "nv",
    direction: "BEARISH",
    sort: "score_7d",
  });
});

test("unknown URL values fall back to defaults", () => {
  assert.deepEqual(app.parseFilters("?direction=bogus&sort=bogus"), {
    q: "",
    direction: "ALL",
    sort: "ticker",
  });
});

test("hash routes to a ticker detail or back to the board", () => {
  assert.deepEqual(app.parseRoute("#/aapl"), { name: "detail", ticker: "AAPL" });
  assert.deepEqual(app.parseRoute(""), { name: "board", ticker: null });
  assert.deepEqual(app.parseRoute("#/"), { name: "board", ticker: null });
});

test("view URL round-trips through the parsers", () => {
  const url = app.buildViewUrl(
    "/index.html",
    { q: "nv", direction: "BULLISH", sort: "score_7d" },
    { name: "detail", ticker: "NVDA" }
  );
  assert.equal(url, "/index.html?q=nv&direction=BULLISH&sort=score_7d#/NVDA");
  const query = url.slice(url.indexOf("?"), url.indexOf("#"));
  assert.deepEqual(app.parseFilters(query), {
    q: "nv",
    direction: "BULLISH",
    sort: "score_7d",
  });
  assert.deepEqual(app.parseRoute("#/NVDA"), { name: "detail", ticker: "NVDA" });
});

test("a reloaded filtered URL yields the same visible tickers", () => {
  const stocks = [
    makeStock({ ticker: "NVDA", summary_json: { direction: "BULLISH" } }),
    makeStock({ ticker: "NVAX", summary_json: { direction: "BEARISH" } }),
    makeStock({ ticker: "MSFT", summary_json: { direction: "BULLISH" } }),
  ];

  const filters = app.parseFilters("?q=nv&direction=BULLISH");
  assert.deepEqual(app.selectStocks(stocks, filters).map((s) => s.ticker), ["NVDA"]);
});

// --- UX-1: text fallback ------------------------------------------------------

test("assessment falls back to the text body and stops at section headings", () => {
  const stock = {
    ticker: "X",
    status: "fresh",
    summary_json: {},
    summary_text_body: "Prose here.\n\nPrimary drivers:\n- something",
  };
  assert.equal(app.assessmentFor(stock), "Prose here.");
});

test("assessment prefers structured JSON over the text body", () => {
  const stock = makeStock({
    summary_text_body: "Stale prose.\n\nPrimary drivers:\n- old",
  });
  assert.equal(app.assessmentFor(stock), "Services momentum offsets hardware softness.");
});

// --- safety ------------------------------------------------------------------

test("escapeHtml neutralises markup", () => {
  assert.equal(app.escapeHtml('<script>"x"</script>'), "&lt;script&gt;&quot;x&quot;&lt;/script&gt;");
});

test("card escapes hostile summary content", () => {
  const stock = makeStock({ summary_json: { summary: "<img src=x onerror=alert(1)>" } });
  const html = app.buildCardHtml(stock);
  assert.equal(html.includes("<img src=x"), false);
  assert.equal(html.includes("&lt;img src=x"), true);
});
