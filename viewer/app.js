const state = {
  analysisPath: '',
  refreshedAt: '',
  stocks: [],
};

const stockGrid = document.getElementById('stock-grid');
const stockCount = document.getElementById('stock-count');
const lastRefresh = document.getElementById('last-refresh');
const analysisPath = document.getElementById('analysis-path');
const refreshButton = document.getElementById('refresh-button');

refreshButton.addEventListener('click', () => {
  hydrateState().then(render);
});

hydrateState().then(render);
setInterval(() => {
  hydrateState().then(render);
}, 60 * 1000);

async function hydrateState() {
  const response = await fetch('/api/stocks', { cache: 'no-store' });
  const payload = await response.json();

  state.analysisPath = payload.analysis_path;
  state.refreshedAt = payload.refreshed_at;
  state.stocks = Array.isArray(payload.stocks) ? payload.stocks : [];
}

function render() {
  stockCount.textContent = `${state.stocks.length} ${state.stocks.length === 1 ? 'ticker' : 'tickers'}`;
  lastRefresh.textContent = state.refreshedAt ? `Synced ${formatDateTime(state.refreshedAt)}` : 'Waiting for data';
  analysisPath.textContent = state.analysisPath || 'Unavailable';

  if (state.stocks.length === 0) {
    const empty = document.createElement('article');
    empty.className = 'empty-state';
    empty.textContent = 'No stock folders were found in the mounted analysis directory.';
    stockGrid.replaceChildren(empty);
    return;
  }

  stockGrid.replaceChildren(...state.stocks.map(createStockCard));
}

function createStockCard(stock) {
  const card = document.createElement('article');
  card.className = 'stock-card';

  const data = stock.summary_json || {};
  const header = document.createElement('header');
  header.className = 'card-header';

  const headerText = document.createElement('div');
  const ticker = document.createElement('p');
  ticker.className = 'ticker';
  ticker.textContent = stock.ticker;

  const company = document.createElement('h2');
  company.textContent = data.company_name || stock.ticker;

  const sector = document.createElement('p');
  sector.className = 'subtle';
  sector.textContent = data.sector || 'Sector unavailable';
  headerText.append(ticker, company, sector);

  const sentiment = document.createElement('div');
  sentiment.className = `sentiment-pill sentiment-pill--${String(data.direction || 'unknown').toLowerCase()}`;
  sentiment.textContent = data.direction || 'UNKNOWN';
  header.append(headerText, sentiment);

  const summary = document.createElement('p');
  summary.className = 'summary';
  summary.textContent = stock.summary_text || data.summary || 'No summary available.';

  const metrics = document.createElement('dl');
  metrics.className = 'metrics';
  appendMetric(metrics, 'Confidence', formatPercent(data.confidence_pct));
  appendMetric(metrics, '7d docs', formatNumber(data.document_count_7d));
  appendMetric(metrics, '1d score', formatScore(data.composite_score_1d));
  appendMetric(metrics, '7d score', formatScore(data.composite_score_7d));
  appendMetric(metrics, '30d score', formatScore(data.composite_score_30d));
  appendMetric(metrics, 'Updated', formatDateTime(stock.last_updated || data.generated_at));

  const sections = document.createElement('div');
  sections.className = 'sections';
  sections.append(
    createListSection('Primary drivers', data.primary_drivers),
    createListSection('Primary risks', data.primary_risks),
    createConflictSection(data.conflicts),
    createEventsSection(data.top_events),
  );

  const rawDetails = document.createElement('details');
  rawDetails.className = 'raw-json';
  const rawSummary = document.createElement('summary');
  rawSummary.textContent = 'View summary.json';
  const pre = document.createElement('pre');
  pre.textContent = JSON.stringify(data, null, 2);
  rawDetails.append(rawSummary, pre);

  card.append(header, summary, metrics, sections, rawDetails);
  return card;
}

function appendMetric(metrics, label, value) {
  const wrapper = document.createElement('div');
  const term = document.createElement('dt');
  const description = document.createElement('dd');

  term.textContent = label;
  description.textContent = value;
  wrapper.append(term, description);
  metrics.append(wrapper);
}

function createListSection(title, items) {
  const section = document.createElement('section');
  section.className = 'detail-section';
  const heading = document.createElement('h3');
  heading.textContent = title;

  const list = document.createElement('ul');
  const values = Array.isArray(items) ? items : [];

  if (values.length === 0) {
    const item = document.createElement('li');
    item.className = 'empty-copy';
    item.textContent = 'No items available.';
    list.append(item);
  } else {
    values.forEach((value) => {
      const item = document.createElement('li');
      item.textContent = String(value);
      list.append(item);
    });
  }

  section.append(heading, list);
  return section;
}

function createConflictSection(conflicts) {
  const section = document.createElement('section');
  section.className = 'detail-section';
  const heading = document.createElement('h3');
  heading.textContent = 'Conflicts';
  section.append(heading);

  const values = Array.isArray(conflicts) ? conflicts : [];
  if (values.length === 0) {
    const copy = document.createElement('p');
    copy.className = 'empty-copy';
    copy.textContent = 'No conflicts reported.';
    section.append(copy);
    return section;
  }

  const list = document.createElement('ul');
  values.forEach((conflict) => {
    const item = document.createElement('li');
    const severity = document.createElement('span');
    severity.className = 'tag';
    severity.textContent = conflict.severity || 'INFO';
    const description = document.createElement('span');
    description.textContent = conflict.description || 'No description';
    item.append(severity, description);
    list.append(item);
  });
  section.append(list);
  return section;
}

function createEventsSection(events) {
  const section = document.createElement('section');
  section.className = 'detail-section detail-section--events';
  const heading = document.createElement('h3');
  heading.textContent = 'Top events';
  section.append(heading);

  const values = Array.isArray(events) ? events.slice(0, 5) : [];
  if (values.length === 0) {
    const copy = document.createElement('p');
    copy.className = 'empty-copy';
    copy.textContent = 'No events available.';
    section.append(copy);
    return section;
  }

  const list = document.createElement('ul');
  values.forEach((event) => {
    const item = document.createElement('li');
    const headline = document.createElement('strong');
    headline.textContent = event.headline || 'Untitled event';
    const meta = document.createElement('span');
    meta.className = 'subtle';
    meta.textContent = `${event.date || 'Unknown date'} · ${event.importance || 'Unknown importance'} · ${formatScore(event.score)}`;
    item.append(headline, meta);
    list.append(item);
  });
  section.append(list);
  return section;
}

function formatPercent(value) {
  return Number.isFinite(value) ? `${value}%` : 'N/A';
}

function formatNumber(value) {
  return Number.isFinite(value) ? value.toLocaleString() : 'N/A';
}

function formatScore(value) {
  return Number.isFinite(value) ? value.toFixed(3) : 'N/A';
}

function formatDateTime(value) {
  if (!value) {
    return 'N/A';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}