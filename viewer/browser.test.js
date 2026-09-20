/**
 * Integration tests for the viewer's DOM wiring and routing.
 *
 * app.js is executed inside a `node:vm` context with a minimal fake DOM so the
 * browser-only init path runs for real: fetch -> filter -> render, hash routing,
 * and control wiring.
 *
 * Run with: node --test viewer/
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");

function makeCard(ticker, company, direction, score, extras) {
  return Object.assign(
    {
      ticker: ticker,
      status: "fresh",
      last_updated: "2026-09-13T09:00:00+00:00",
      coverage: { level: "high", document_count_7d: 120 },
      summary_json: {
        company_name: company,
        sector: "Technology",
        direction: direction,
        confidence_pct: 70,
        summary: company + " assessment.",
        primary_drivers: ["Driver for " + ticker],
        primary_risks: ["Risk for " + ticker],
        conflicts: [],
        top_events: [],
        composite_score_7d: score,
        composite_score_1d: null,
        composite_score_30d: null,
        document_count_7d: 120,
      },
    },
    extras || {}
  );
}

const STOCKS = [
  makeCard("AAPL", "Apple Inc", "BULLISH", 0.2),
  makeCard("NVDA", "NVIDIA Corp", "BULLISH", 0.9),
  makeCard("GRMN", "Garmin Ltd", "BEARISH", 0.1),
];

function makeElement(id) {
  const listeners = {};
  return {
    id: id,
    value: "",
    textContent: "",
    innerHTML: "",
    hidden: false,
    listeners: listeners,
    addEventListener: function (type, handler) {
      (listeners[type] || (listeners[type] = [])).push(handler);
    },
    dispatch: function (type, event) {
      (listeners[type] || []).forEach(function (handler) {
        handler(event || {});
      });
    },
    closest: function () {
      return null;
    },
  };
}

const ELEMENT_IDS = [
  "search-input",
  "direction-filter",
  "sort-select",
  "reset-button",
  "refresh-button",
  "result-count",
  "last-refresh",
  "analysis-path",
  "stock-grid",
  "board-view",
  "detail-view",
];

function createApp(options) {
  const opts = options || {};
  const elements = {};
  ELEMENT_IDS.forEach(function (id) {
    elements[id] = makeElement(id);
  });
  elements["direction-filter"].value = "ALL";
  elements["sort-select"].value = "ticker";

  const windowListeners = {};
  const windowObject = {
    location: { pathname: "/", search: opts.search || "", hash: opts.hash || "" },
    history: {
      replaceState: function (state, title, url) {
        applyUrl(url);
      },
    },
    addEventListener: function (type, handler) {
      (windowListeners[type] || (windowListeners[type] = [])).push(handler);
    },
    scrollTo: function () {},
  };

  function applyUrl(url) {
    const hashIndex = url.indexOf("#");
    const hash = hashIndex === -1 ? "" : url.slice(hashIndex);
    const withoutHash = hashIndex === -1 ? url : url.slice(0, hashIndex);
    const queryIndex = withoutHash.indexOf("?");
    windowObject.location.pathname =
      queryIndex === -1 ? withoutHash : withoutHash.slice(0, queryIndex);
    windowObject.location.search = queryIndex === -1 ? "" : withoutHash.slice(queryIndex);
    windowObject.location.hash = hash;
  }

  const calls = [];

  function fakeFetch(url) {
    calls.push(url);
    if (url === "/api/stocks") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: function () {
          return Promise.resolve({
            analysis_path: "/srv/analysis",
            refreshed_at: "2026-09-13T09:41:02+00:00",
            stocks: STOCKS,
          });
        },
      });
    }
    const ticker = url.replace("/api/stocks/", "");
    const match = STOCKS.find(function (stock) {
      return stock.ticker === ticker;
    });
    if (!match) {
      return Promise.resolve({
        ok: false,
        status: 404,
        json: function () {
          return Promise.resolve({ error: { code: "ticker_not_found" } });
        },
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function () {
        return Promise.resolve(match);
      },
    });
  }

  const sandbox = {
    document: {
      getElementById: function (id) {
        return elements[id] || null;
      },
    },
    window: windowObject,
    fetch: fakeFetch,
    URLSearchParams: URLSearchParams,
    Intl: Intl,
    console: console,
    setTimeout: setTimeout,
    decodeURIComponent: decodeURIComponent,
    encodeURIComponent: encodeURIComponent,
  };
  sandbox.globalThis = sandbox;

  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox);

  function navigate(hash) {
    windowObject.location.hash = hash;
    (windowListeners.hashchange || []).forEach(function (handler) {
      handler({});
    });
  }

  async function settle() {
    for (let index = 0; index < 5; index += 1) {
      await new Promise(function (resolve) {
        setTimeout(resolve, 0);
      });
    }
  }

  return { elements: elements, window: windowObject, calls: calls, navigate: navigate, settle: settle };
}

// --- initial render ----------------------------------------------------------

test("board renders every ticker and shows the result count", async () => {
  const app = createApp();
  await app.settle();

  const grid = app.elements["stock-grid"].innerHTML;
  assert.equal(grid.includes("data-ticker=\"AAPL\""), true);
  assert.equal(grid.includes("data-ticker=\"NVDA\""), true);
  assert.equal(grid.includes("data-ticker=\"GRMN\""), true);
  assert.equal(app.elements["result-count"].textContent, "3 tickers");
  assert.equal(grid.includes("Generated:"), false);
  assert.equal(app.elements["analysis-path"].textContent, "/srv/analysis");
});

// --- UX-2: search, filter, sort wiring ---------------------------------------

test("typing in search narrows the grid live", async () => {
  const app = createApp();
  await app.settle();

  app.elements["search-input"].value = "nv";
  app.elements["search-input"].dispatch("input", {});

  const grid = app.elements["stock-grid"].innerHTML;
  assert.equal(grid.includes("data-ticker=\"NVDA\""), true);
  assert.equal(grid.includes("data-ticker=\"AAPL\""), false);
  assert.equal(app.elements["result-count"].textContent, "1 of 3 tickers");
  assert.equal(app.window.location.search, "?q=nv");
});

test("direction filter keeps only matching cards", async () => {
  const app = createApp();
  await app.settle();

  app.elements["direction-filter"].value = "BEARISH";
  app.elements["direction-filter"].dispatch("change", {});

  const grid = app.elements["stock-grid"].innerHTML;
  assert.equal(grid.includes("data-ticker=\"GRMN\""), true);
  assert.equal(grid.includes("data-ticker=\"AAPL\""), false);
  assert.equal(app.elements["result-count"].textContent, "1 of 3 tickers");
});

test("sort control reorders the grid", async () => {
  const app = createApp();
  await app.settle();

  app.elements["sort-select"].value = "score_7d";
  app.elements["sort-select"].dispatch("change", {});

  const grid = app.elements["stock-grid"].innerHTML;
  assert.equal(grid.indexOf("data-ticker=\"NVDA\"") < grid.indexOf("data-ticker=\"AAPL\""), true);
  assert.equal(app.window.location.search, "?sort=score_7d");
});

test("Escape clears the search box", async () => {
  const app = createApp();
  await app.settle();

  app.elements["search-input"].value = "nv";
  app.elements["search-input"].dispatch("input", {});
  app.elements["search-input"].dispatch("keydown", { key: "Escape" });

  assert.equal(app.elements["search-input"].value, "");
  assert.equal(app.elements["result-count"].textContent, "3 tickers");
  assert.equal(app.window.location.search, "");
});

test("no-match search shows a distinct empty state", async () => {
  const app = createApp();
  await app.settle();

  app.elements["search-input"].value = "zzzz";
  app.elements["search-input"].dispatch("input", {});

  const grid = app.elements["stock-grid"].innerHTML;
  assert.equal(grid.includes("No tickers match"), true);
  assert.equal(app.elements["result-count"].textContent, "0 of 3 tickers");
});

// --- UX-2: reloading a filtered URL ------------------------------------------

test("reloading a filtered URL restores the same view", async () => {
  const app = createApp({ search: "?q=nv&direction=BULLISH" });
  await app.settle();

  assert.equal(app.elements["search-input"].value, "nv");
  assert.equal(app.elements["direction-filter"].value, "BULLISH");

  const grid = app.elements["stock-grid"].innerHTML;
  assert.equal(grid.includes("data-ticker=\"NVDA\""), true);
  assert.equal(grid.includes("data-ticker=\"AAPL\""), false);
  assert.equal(app.elements["result-count"].textContent, "1 of 3 tickers");
});

// --- UX-3: detail routing ----------------------------------------------------

test("hash navigation opens the ticker detail view", async () => {
  const app = createApp();
  await app.settle();

  app.navigate("#/AAPL");
  await app.settle();

  assert.equal(app.elements["board-view"].hidden, true);
  assert.equal(app.elements["detail-view"].hidden, false);
  const detail = app.elements["detail-view"].innerHTML;
  assert.equal(detail.includes("Apple Inc"), true);
  assert.equal(detail.includes("Back to board"), true);
  assert.equal(detail.includes("Raw export"), true);
  assert.equal(app.calls.includes("/api/stocks/AAPL"), true);
});

test("unknown ticker shows a friendly not-found state", async () => {
  const app = createApp({ hash: "#/ZZZZ" });
  await app.settle();

  const detail = app.elements["detail-view"].innerHTML;
  assert.equal(detail.includes("ZZZZ not found"), true);
  assert.equal(detail.includes("Back to board"), true);
});

test("returning to the board keeps the active filters", async () => {
  const app = createApp({ search: "?q=nv&direction=BULLISH" });
  await app.settle();

  app.navigate("#/NVDA");
  await app.settle();
  assert.equal(app.elements["board-view"].hidden, true);

  app.navigate("");
  await app.settle();

  assert.equal(app.elements["board-view"].hidden, false);
  assert.equal(app.elements["detail-view"].hidden, true);
  assert.equal(app.elements["search-input"].value, "nv");
  assert.equal(app.elements["direction-filter"].value, "BULLISH");
  assert.equal(app.elements["result-count"].textContent, "1 of 3 tickers");
});

// --- UX-4: badges in the DOM -------------------------------------------------

test("status and coverage badges reach the rendered grid", async () => {
  const app = createApp();
  await app.settle();

  const grid = app.elements["stock-grid"].innerHTML;
  assert.equal(grid.includes("status-chip--fresh"), true);
  assert.equal(grid.includes("Strong evidence"), true);
  assert.equal(grid.includes("No items available."), false);
});
