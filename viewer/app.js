/**
 * Stock Analysis Board.
 *
 * The view logic is written as pure functions (data in, HTML out) so it can be
 * unit tested under `node --test`. The DOM wiring lives in initBrowser() and only
 * runs when a document exists.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ViewerApp = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var STATUS_LABELS = {
    fresh: "Fresh",
    recent: "Recent",
    stale: "Stale",
    failed: "Failed",
    no_data: "No data",
  };

  var COVERAGE_LABELS = {
    unknown: "Coverage unknown",
    low: "Low evidence",
    medium: "Moderate evidence",
    high: "Strong evidence",
  };

  var DIRECTIONS = ["ALL", "BULLISH", "BEARISH", "MIXED", "NEUTRAL"];
  var SORT_OPTIONS = ["ticker", "updated", "confidence", "score_7d"];

  var TIER_LABELS = {
    tier_1: "Tier 1 — SEC filings",
    tier_2: "Tier 2 — Executive comms",
    tier_3: "Tier 3 — Financial news",
    tier_4: "Tier 4 — Social media",
    tier_5: "Tier 5 — WallStreetBets",
  };

  var HEADER_PREFIXES = ["generated:", "source:", "direction:", "confidence:", "assessment:"];
  var SECTION_LABELS = ["primary drivers:", "primary risks:", "conflicts:", "top events:"];

  function text(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function escapeHtml(value) {
    return text(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function jsonFor(stock) {
    var data = stock && stock.summary_json;
    return data && typeof data === "object" ? data : {};
  }

  function tickerFor(stock) {
    return text(stock && stock.ticker);
  }

  function companyName(stock) {
    return text(jsonFor(stock).company_name) || tickerFor(stock);
  }

  function sectorFor(stock) {
    return text(jsonFor(stock).sector) || "Sector unavailable";
  }

  function normaliseDirection(value) {
    var normalised = text(value).trim().toUpperCase();
    return normalised || "UNKNOWN";
  }

  function stockDirection(stock) {
    var data = jsonFor(stock);
    var value = stock && stock.direction ? stock.direction : data.direction;
    return normaliseDirection(value);
  }

  function confidenceFor(stock) {
    var value = jsonFor(stock).confidence_pct;
    return typeof value === "number" && isFinite(value) ? value : null;
  }

  function score7dFor(stock) {
    var value = jsonFor(stock).composite_score_7d;
    return typeof value === "number" && isFinite(value) ? value : null;
  }

  function stripSummaryHeader(value) {
    var body = text(value).trim();
    if (!body) {
      return "";
    }

    var lines = body.split(/\r?\n/);
    var hasHeader = lines.slice(0, 5).some(function (line) {
      var lowered = line.trim().toLowerCase();
      return HEADER_PREFIXES.some(function (prefix) {
        return lowered.indexOf(prefix) === 0;
      });
    });
    if (!hasHeader) {
      return body;
    }

    var blankIndex = lines.findIndex(function (line) {
      return !line.trim();
    });
    if (blankIndex === -1) {
      return "";
    }

    var result = lines.slice(blankIndex + 1);
    if (result.length && result[0].trim().toLowerCase().replace(/:$/, "") === "assessment") {
      result = result.slice(1);
    }
    return result.join("\n").trim();
  }

  function extractAssessmentBody(value) {
    var body = text(value).trim();
    if (!body) {
      return "";
    }
    var lines = body.split(/\r?\n/);
    for (var index = 0; index < lines.length; index += 1) {
      if (SECTION_LABELS.indexOf(lines[index].trim().toLowerCase()) !== -1) {
        return lines.slice(0, index).join("\n").trim();
      }
    }
    return body;
  }

  function assessmentFor(stock) {
    if (stock && typeof stock.assessment === "string" && stock.assessment.trim()) {
      return stock.assessment.trim();
    }
    var summary = jsonFor(stock).summary;
    if (typeof summary === "string" && summary.trim()) {
      return summary.trim();
    }
    return extractAssessmentBody((stock && (stock.summary_text_body || stock.summary_text)) || "");
  }

  function errorFor(stock) {
    if (stock && typeof stock.error_message === "string" && stock.error_message.trim()) {
      return stock.error_message.trim();
    }
    var fallback = jsonFor(stock).error;
    return typeof fallback === "string" ? fallback.trim() : "";
  }

  function resolveStatus(stock) {
    var status = stock && stock.status;
    if (typeof status === "string" && Object.prototype.hasOwnProperty.call(STATUS_LABELS, status)) {
      return status;
    }
    return stock && stock.last_updated ? "recent" : "no_data";
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || STATUS_LABELS.no_data;
  }

  function coverageFor(stock) {
    var coverage = stock && stock.coverage;
    if (coverage && typeof coverage === "object") {
      return coverage;
    }
    return { level: "unknown", document_count_7d: null };
  }

  function formatPercent(value) {
    return typeof value === "number" && isFinite(value) ? value + "%" : "N/A";
  }

  function formatNumber(value) {
    return typeof value === "number" && isFinite(value) ? value.toLocaleString() : "N/A";
  }

  function formatScore(value) {
    return typeof value === "number" && isFinite(value) ? value.toFixed(3) : "N/A";
  }

  function formatDateTime(value) {
    if (!value) {
      return "N/A";
    }
    var date = new Date(value);
    if (isNaN(date.getTime())) {
      return text(value);
    }
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function compareNullableNumbers(first, second, direction) {
    var a = typeof first === "number" && isFinite(first) ? first : null;
    var b = typeof second === "number" && isFinite(second) ? second : null;
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return direction === "asc" ? a - b : b - a;
  }

  function compareNullableDates(first, second) {
    var a = first ? Date.parse(first) : NaN;
    var b = second ? Date.parse(second) : NaN;
    var aValid = isFinite(a) ? a : null;
    var bValid = isFinite(b) ? b : null;
    if (aValid === null && bValid === null) return 0;
    if (aValid === null) return 1;
    if (bValid === null) return -1;
    return bValid - aValid;
  }

  function applyFilters(stocks, filters) {
    var query = text(filters && filters.q).trim().toLowerCase();
    var direction = normaliseDirection((filters && filters.direction) || "ALL");

    return (stocks || []).filter(function (stock) {
      if (direction !== "ALL" && stockDirection(stock) !== direction) {
        return false;
      }
      if (!query) {
        return true;
      }
      var haystack = [tickerFor(stock), companyName(stock), sectorFor(stock)]
        .join(" ")
        .toLowerCase();
      return haystack.indexOf(query) !== -1;
    });
  }

  function sortStocks(stocks, sortKey) {
    var key = SORT_OPTIONS.indexOf(sortKey) >= 0 ? sortKey : SORT_OPTIONS[0];

    return (stocks || []).slice().sort(function (a, b) {
      var result;
      if (key === "confidence") {
        result = compareNullableNumbers(confidenceFor(a), confidenceFor(b), "desc");
      } else if (key === "score_7d") {
        result = compareNullableNumbers(score7dFor(a), score7dFor(b), "desc");
      } else if (key === "updated") {
        result = compareNullableDates(a && a.last_updated, b && b.last_updated);
      } else {
        result = tickerFor(a).localeCompare(tickerFor(b));
      }
      return result !== 0 ? result : tickerFor(a).localeCompare(tickerFor(b));
    });
  }

  function selectStocks(stocks, filters) {
    var filtered = applyFilters(stocks, filters);
    return sortStocks(filtered, filters && filters.sort);
  }

  function countLabel(shown, total) {
    if (!total) {
      return "0 tickers";
    }
    if (shown === total) {
      return total + (total === 1 ? " ticker" : " tickers");
    }
    return shown + " of " + total + " tickers";
  }

  function metricHtml(label, value) {
    return (
      "<div><dt>" +
      escapeHtml(label) +
      "</dt><dd>" +
      escapeHtml(value) +
      "</dd></div>"
    );
  }

  function metricsHtml(stock, options) {
    var data = jsonFor(stock);
    var detail = options && options.detail;
    var rows = [
      metricHtml("Confidence", formatPercent(confidenceFor(stock))),
      metricHtml("7d docs", formatNumber(data.document_count_7d)),
      metricHtml("1d score", formatScore(data.composite_score_1d)),
      metricHtml("7d score", formatScore(data.composite_score_7d)),
      metricHtml("30d score", formatScore(data.composite_score_30d)),
    ];
    if (detail) {
      rows.push(metricHtml("Trend", text(data.trend) || "unknown"));
    }
    rows.push(metricHtml("Updated", formatDateTime(stock && stock.last_updated)));
    return '<dl class="metrics">' + rows.join("") + "</dl>";
  }

  function hasMetrics(stock) {
    var data = jsonFor(stock);
    return (
      confidenceFor(stock) !== null ||
      data.document_count_7d !== null && data.document_count_7d !== undefined ||
      typeof data.composite_score_1d === "number" ||
      typeof data.composite_score_7d === "number" ||
      typeof data.composite_score_30d === "number"
    );
  }

  function evidenceHintHtml(stock) {
    var coverage = coverageFor(stock);
    var level = Object.prototype.hasOwnProperty.call(COVERAGE_LABELS, coverage.level)
      ? coverage.level
      : "unknown";
    var documents = coverage.document_count_7d;
    var detail =
      typeof documents === "number"
        ? documents + (documents === 1 ? " document (7d)" : " documents (7d)")
        : "no 7-day document count";
    return (
      '<p class="evidence-hint evidence-hint--' +
      level +
      '">' +
      escapeHtml(COVERAGE_LABELS[level]) +
      " · " +
      escapeHtml(detail) +
      "</p>"
    );
  }

  function sectionHtml(title, innerHtml) {
    return (
      '<section class="detail-section"><h3>' +
      escapeHtml(title) +
      "</h3>" +
      innerHtml +
      "</section>"
    );
  }

  function listSectionHtml(title, items) {
    var values = Array.isArray(items) ? items.filter(function (item) {
      return text(item).trim();
    }) : [];
    if (!values.length) {
      return "";
    }
    var list = values
      .map(function (item) {
        return "<li>" + escapeHtml(item) + "</li>";
      })
      .join("");
    return sectionHtml(title, "<ul>" + list + "</ul>");
  }

  function conflictsSectionHtml(conflicts) {
    var values = Array.isArray(conflicts) ? conflicts : [];
    if (!values.length) {
      return "";
    }
    var list = values
      .map(function (conflict) {
        var severity = text(conflict && conflict.severity) || "INFO";
        var description = text(conflict && conflict.description) || "No description";
        return (
          '<li><span class="tag tag--' +
          escapeHtml(severity.toLowerCase()) +
          '">' +
          escapeHtml(severity) +
          "</span>" +
          escapeHtml(description) +
          "</li>"
        );
      })
      .join("");
    return sectionHtml("Conflicts", "<ul>" + list + "</ul>");
  }

  function eventsSectionHtml(events, limit) {
    var values = Array.isArray(events) ? events : [];
    if (typeof limit === "number" && limit > 0) {
      values = values.slice(0, limit);
    }
    if (!values.length) {
      return "";
    }
    var list = values
      .map(function (event) {
        var headline = text(event && event.headline) || "Untitled event";
        var type = text(event && event.type) || "event";
        var meta = [text(event && event.date) || "Unknown date", type, formatScore(event && event.score)].join(" · ");
        return (
          "<li><strong>" +
          escapeHtml(headline) +
          '</strong><span class="subtle">' +
          escapeHtml(meta) +
          "</span></li>"
        );
      })
      .join("");
    return sectionHtml("Top events", '<ul class="events">' + list + "</ul>");
  }

  function breakdownSectionHtml(breakdown) {
    var data = breakdown && typeof breakdown === "object" ? breakdown : {};
    var keys = Object.keys(data).sort();
    if (!keys.length) {
      return "";
    }
    var list = keys
      .map(function (key) {
        var info = data[key] || {};
        var label = TIER_LABELS[key] || key;
        var value = formatScore(info.score) + " · " + formatNumber(info.count) + " docs";
        return (
          '<li><span>' +
          escapeHtml(label) +
          '</span><span class="subtle">' +
          escapeHtml(value) +
          "</span></li>"
        );
      })
      .join("");
    return sectionHtml("Source breakdown", '<ul class="tier-list">' + list + "</ul>");
  }

  function macroSectionHtml(macro) {
    if (!macro || typeof macro !== "object" || !Object.keys(macro).length) {
      return "";
    }
    var rows = [
      metricHtml("Score", formatScore(macro.score)),
      metricHtml("Dominant factor", text(macro.dominant_factor) || "unknown"),
      metricHtml("Description", text(macro.description) || "No description"),
    ].join("");
    return sectionHtml("Macro overlay", '<dl class="metrics metrics--wide">' + rows + "</dl>");
  }

  function sectionsHtml(stock, options) {
    var data = jsonFor(stock);
    var limit = options && options.eventLimit;
    var sections = [
      listSectionHtml("Primary drivers", data.primary_drivers),
      listSectionHtml("Primary risks", data.primary_risks),
      conflictsSectionHtml(data.conflicts),
      eventsSectionHtml(data.top_events, limit),
    ].filter(Boolean);

    if (options && options.detail) {
      sections.push(breakdownSectionHtml(data.source_breakdown));
      sections.push(macroSectionHtml(data.macro_overlay));
    }

    if (!sections.length) {
      return (
        '<div class="sections"><p class="limited-evidence">Limited evidence — no drivers, risks, ' +
        "conflicts, or events were reported for this ticker.</p></div>"
      );
    }
    return '<div class="sections">' + sections.join("") + "</div>";
  }

  function provenanceHtml(stock) {
    var bits = [];
    if (stock && stock.model) {
      bits.push("Model: " + stock.model);
    }
    bits.push(stock && stock.from_cache ? "Result served from cache" : "Result generated by this run");
    var notes = stock && Array.isArray(stock.notes) ? stock.notes : [];
    notes.forEach(function (note) {
      if (text(note).trim()) {
        bits.push(text(note).trim());
      }
    });
    return '<p class="provenance">' + escapeHtml(bits.join(" · ")) + "</p>";
  }

  function rawExportHtml(stock) {
    var blocks = [];
    if (stock && text(stock.summary_text).trim()) {
      blocks.push(
        '<h4 class="raw-json__heading">summary.txt</h4><pre>' +
          escapeHtml(stock.summary_text) +
          "</pre>"
      );
    }
    var data = jsonFor(stock);
    if (Object.keys(data).length) {
      blocks.push(
        '<h4 class="raw-json__heading">summary.json</h4><pre>' +
          escapeHtml(JSON.stringify(data, null, 2)) +
          "</pre>"
      );
    }
    if (!blocks.length) {
      return "";
    }
    return '<details class="raw-json"><summary>Raw export</summary>' + blocks.join("") + "</details>";
  }

  function detailLinkHtml(stock) {
    var href = "#/" + encodeURIComponent(tickerFor(stock));
    return (
      '<p class="ticker"><a href="' +
      href +
      '">' +
      escapeHtml(tickerFor(stock)) +
      "</a></p>" +
      '<h2><a href="' +
      href +
      '">' +
      escapeHtml(companyName(stock)) +
      "</a></h2>"
    );
  }

  function statusChipHtml(stock) {
    var status = resolveStatus(stock);
    return (
      '<span class="status-chip status-chip--' +
      status +
      '">' +
      escapeHtml(statusLabel(status)) +
      "</span>"
    );
  }

  function sentimentPillHtml(stock) {
    var status = resolveStatus(stock);
    var direction = stockDirection(stock);
    if (status === "failed" || status === "no_data" || direction === "UNKNOWN") {
      return "";
    }
    return (
      '<span class="sentiment-pill sentiment-pill--' +
      direction.toLowerCase() +
      '">' +
      escapeHtml(direction) +
      "</span>"
    );
  }

  function bodyHtml(stock) {
    var status = resolveStatus(stock);
    if (status === "failed") {
      return '<p class="error-block">' + escapeHtml(errorFor(stock) || "Analysis failed.") + "</p>";
    }
    if (status === "no_data") {
      return '<p class="empty-copy">No analysis has been generated for this ticker yet.</p>';
    }
    return '<p class="summary">' + escapeHtml(assessmentFor(stock) || "No assessment available.") + "</p>";
  }

  function buildCardHtml(stock) {
    var status = resolveStatus(stock);
    var badges = [statusChipHtml(stock), sentimentPillHtml(stock)].filter(Boolean).join("");
    var parts = [
      '<header class="card-header"><div class="card-header__text">' +
        detailLinkHtml(stock) +
        '<p class="subtle">' +
        escapeHtml(sectorFor(stock)) +
        "</p></div>" +
        '<div class="card-header__badges">' +
        badges +
        "</div></header>",
      bodyHtml(stock),
      evidenceHintHtml(stock),
    ];

    if (hasMetrics(stock)) {
      parts.push(metricsHtml(stock));
    }
    parts.push(sectionsHtml(stock, { eventLimit: 3 }));
    parts.push(provenanceHtml(stock));

    return (
      '<article class="stock-card" data-ticker="' +
      escapeHtml(tickerFor(stock)) +
      '" data-status="' +
      status +
      '">' +
      parts.join("") +
      "</article>"
    );
  }

  function buildGridHtml(selected, total) {
    if (!total) {
      return '<article class="empty-state">No stock folders were found in the mounted analysis directory.</article>';
    }
    if (!selected.length) {
      return (
        '<article class="empty-state">No tickers match the current search or filter. ' +
        '<button type="button" class="ghost-button" data-action="reset">Reset filters</button></article>'
      );
    }
    return selected.map(buildCardHtml).join("");
  }

  function buildDetailHtml(stock) {
    var status = resolveStatus(stock);
    var badges = [statusChipHtml(stock), sentimentPillHtml(stock)].filter(Boolean).join("");
    var parts = [
      '<a class="back-link" href="#">← Back to board</a>',
      '<article class="detail-card" data-ticker="' +
        escapeHtml(tickerFor(stock)) +
        '" data-status="' +
        status +
        '">',
      '<header class="detail-header"><div><p class="ticker">' +
        escapeHtml(tickerFor(stock)) +
        "</p><h1>" +
        escapeHtml(companyName(stock)) +
        '</h1><p class="subtle">' +
        escapeHtml(sectorFor(stock)) +
        '</p></div><div class="card-header__badges">' +
        badges +
        "</div></header>",
      bodyHtml(stock),
      evidenceHintHtml(stock),
    ];

    if (hasMetrics(stock)) {
      parts.push(metricsHtml(stock, { detail: true }));
    }
    parts.push(sectionsHtml(stock, { detail: true }));
    parts.push(provenanceHtml(stock));
    parts.push(rawExportHtml(stock));
    parts.push("</article>");

    return parts.join("");
  }

  function buildNotFoundHtml(ticker) {
    var label = text(ticker) || "That ticker";
    return (
      '<a class="back-link" href="#">← Back to board</a>' +
      '<article class="empty-state"><h2>' +
      escapeHtml(label) +
      " not found</h2><p>No analysis bundle exists for this ticker in the mounted analysis directory.</p></article>"
    );
  }

  function parseFilters(search) {
    var params = new URLSearchParams(text(search).replace(/^\?/, ""));
    var direction = normaliseDirection(params.get("direction") || "ALL");
    var sort = params.get("sort") || SORT_OPTIONS[0];
    return {
      q: params.get("q") || "",
      direction: DIRECTIONS.indexOf(direction) !== -1 ? direction : "ALL",
      sort: SORT_OPTIONS.indexOf(sort) !== -1 ? sort : SORT_OPTIONS[0],
    };
  }

  function parseRoute(hash) {
    var value = text(hash).replace(/^#\/?/, "").trim();
    if (!value) {
      return { name: "board", ticker: null };
    }
    var ticker = value;
    try {
      ticker = decodeURIComponent(value);
    } catch (error) {
      ticker = value;
    }
    return { name: "detail", ticker: ticker.toUpperCase() };
  }

  function buildViewUrl(pathname, filters, route) {
    var params = new URLSearchParams();
    if (filters && filters.q) {
      params.set("q", filters.q);
    }
    if (filters && filters.direction && filters.direction !== "ALL") {
      params.set("direction", filters.direction);
    }
    if (filters && filters.sort && filters.sort !== SORT_OPTIONS[0]) {
      params.set("sort", filters.sort);
    }
    var query = params.toString();
    var hash =
      route && route.name === "detail" && route.ticker
        ? "#/" + encodeURIComponent(route.ticker)
        : "";
    return text(pathname) + (query ? "?" + query : "") + hash;
  }

  function initBrowser() {
    var searchInput = document.getElementById("search-input");
    var directionFilter = document.getElementById("direction-filter");
    var sortSelect = document.getElementById("sort-select");
    var resetButton = document.getElementById("reset-button");
    var refreshButton = document.getElementById("refresh-button");
    var resultCount = document.getElementById("result-count");
    var lastRefresh = document.getElementById("last-refresh");
    var analysisPathEl = document.getElementById("analysis-path");
    var stockGrid = document.getElementById("stock-grid");
    var boardView = document.getElementById("board-view");
    var detailView = document.getElementById("detail-view");

    var state = {
      analysisPath: "",
      refreshedAt: "",
      stocks: [],
      filters: { q: "", direction: "ALL", sort: SORT_OPTIONS[0] },
      detail: null,
      route: { name: "board", ticker: null },
    };

    function readUrl() {
      state.filters = parseFilters(window.location.search);
      state.route = parseRoute(window.location.hash);
    }

    function writeUrl() {
      window.history.replaceState(
        null,
        "",
        buildViewUrl(window.location.pathname, state.filters, state.route)
      );
    }

    function syncControls() {
      searchInput.value = state.filters.q;
      directionFilter.value = state.filters.direction;
      sortSelect.value = state.filters.sort;
    }

    function render() {
      lastRefresh.textContent = state.refreshedAt
        ? "Synced " + formatDateTime(state.refreshedAt)
        : "Waiting for data";
      if (analysisPathEl) {
        analysisPathEl.textContent = state.analysisPath || "Unavailable";
      }

      if (state.route.name === "detail") {
        boardView.hidden = true;
        detailView.hidden = false;
        detailView.innerHTML = state.detail
          ? buildDetailHtml(state.detail)
          : buildNotFoundHtml(state.route.ticker);
        return;
      }

      boardView.hidden = false;
      detailView.hidden = true;
      var selected = selectStocks(state.stocks, state.filters);
      resultCount.textContent = countLabel(selected.length, state.stocks.length);
      stockGrid.innerHTML = buildGridHtml(selected, state.stocks.length);
    }

    async function loadBoard() {
      try {
        var response = await fetch("/api/stocks", { cache: "no-store" });
        var payload = await response.json();
        state.analysisPath = payload.analysis_path || "";
        state.refreshedAt = payload.refreshed_at || "";
        state.stocks = Array.isArray(payload.stocks) ? payload.stocks : [];
      } catch (error) {
        state.stocks = [];
        state.refreshedAt = "";
      }
    }

    async function loadDetail(ticker) {
      state.detail = null;
      try {
        var response = await fetch("/api/stocks/" + encodeURIComponent(ticker), {
          cache: "no-store",
        });
        state.detail = response.ok ? await response.json() : null;
      } catch (error) {
        state.detail = null;
      }
    }

    async function refresh() {
      readUrl();
      syncControls();
      await loadBoard();
      if (state.route.name === "detail") {
        await loadDetail(state.route.ticker);
      }
      render();
    }

    async function handleRouteChange() {
      readUrl();
      if (state.route.name === "detail") {
        await loadDetail(state.route.ticker);
      }
      render();
      window.scrollTo({ top: 0, behavior: "auto" });
    }

    function resetFilters() {
      state.filters = { q: "", direction: "ALL", sort: SORT_OPTIONS[0] };
      syncControls();
      writeUrl();
      render();
    }

    searchInput.addEventListener("input", function () {
      state.filters.q = searchInput.value;
      writeUrl();
      render();
    });

    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        searchInput.value = "";
        state.filters.q = "";
        writeUrl();
        render();
      }
    });

    directionFilter.addEventListener("change", function () {
      state.filters.direction = directionFilter.value;
      writeUrl();
      render();
    });

    sortSelect.addEventListener("change", function () {
      state.filters.sort = sortSelect.value;
      writeUrl();
      render();
    });

    resetButton.addEventListener("click", resetFilters);

    stockGrid.addEventListener("click", function (event) {
      if (event.target && event.target.closest('[data-action="reset"]')) {
        resetFilters();
      }
    });

    refreshButton.addEventListener("click", refresh);
    window.addEventListener("hashchange", handleRouteChange);

    refresh();
  }

  var api = {
    STATUS_LABELS: STATUS_LABELS,
    COVERAGE_LABELS: COVERAGE_LABELS,
    DIRECTIONS: DIRECTIONS,
    SORT_OPTIONS: SORT_OPTIONS,
    escapeHtml: escapeHtml,
    stripSummaryHeader: stripSummaryHeader,
    assessmentFor: assessmentFor,
    resolveStatus: resolveStatus,
    coverageFor: coverageFor,
    normaliseDirection: normaliseDirection,
    applyFilters: applyFilters,
    sortStocks: sortStocks,
    selectStocks: selectStocks,
    parseFilters: parseFilters,
    parseRoute: parseRoute,
    buildViewUrl: buildViewUrl,
    countLabel: countLabel,
    formatDateTime: formatDateTime,
    buildCardHtml: buildCardHtml,
    buildDetailHtml: buildDetailHtml,
    buildGridHtml: buildGridHtml,
    buildNotFoundHtml: buildNotFoundHtml,
  };

  if (typeof document !== "undefined") {
    initBrowser();
  }

  return api;
});
