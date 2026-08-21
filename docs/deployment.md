# Deployment and Operations

This project is designed to run well in three common modes:

1. local developer run
2. homelab daemon
3. cloud or VPS service

## Local developer run

This is the recommended first run.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d db
python cli.py db-init
python cli.py add AAPL
python cli.py run --once
python cli.py analyze AAPL --fresh
```

Use this mode when you are still validating credentials, data coverage, or model behavior.

## Homelab daemon mode

For a long-running service that survives shell exits, use the provided user-level systemd units.

### Install the units

```bash
mkdir -p ~/.config/systemd/user
cp ops/systemd/*.service ~/.config/systemd/user/
cp ops/systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
```

If your repo is not checked out at `~/homelab/stock-sentiment-cli`, edit these fields in the copied service files first:

- `WorkingDirectory`
- `ExecStart`

### Always-on daemon

```bash
systemctl --user enable --now stock-sentiment-daemon.service
```

This mode is best when you want workers continuously available.

### Daily one-shot timer

```bash
systemctl --user enable --now stock-sentiment-once.timer
```

This mode is best when one scheduled batch per day is enough.

### Keep services alive after logout

```bash
sudo loginctl enable-linger "$USER"
```

### Restart after code or config changes

```bash
systemctl --user restart stock-sentiment-daemon.service
```

If you changed the unit file itself:

```bash
systemctl --user daemon-reload
```

### Logs and status

```bash
systemctl --user status stock-sentiment-daemon.service
journalctl --user -u stock-sentiment-daemon.service -f
journalctl --user -u stock-sentiment-once.service -n 200 --no-pager
```

## API mode

The API is intentionally narrow. It is useful when another service should request analysis remotely.

Start it with:

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

Endpoints:

- `POST /analyze`
- `GET /status/{ticker}`

The API uses the same database and LLM configuration as the CLI.

## Viewer mode

The viewer is a lightweight browser surface over exported analysis files.

Start it with:

```bash
python viewer/app.py
```

Environment variables:

- `ANALYSIS_DIR` points the viewer at exported summaries
- `VIEWER_PORT` changes the listen port

Defaults are tuned for an in-repo run, so if your analysis exports remain under `output/analysis`, you usually do not need to set either variable.

## Database notes

The root `docker-compose.yml` is intentionally small and only starts TimescaleDB.

```bash
docker compose up -d db
```

It now:

- works without a pre-created external network
- accepts `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` from `.env`

If you change those values, update `DB_URL` and `DB_URL_SYNC` to match.

## LLM provider notes

The analysis layer supports:

- OpenAI
- Anthropic

You can either force a provider with `LLM_PROVIDER` or leave it on `auto`.

Examples:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
```

If `LLM_PROVIDER=auto`, the current precedence is:

1. `OPENAI_API_KEY`
2. `ANTHROPIC_API_KEY`

## Operating notes

### Cache behavior

Analysis results are cached for `AGENT_CACHE_TTL` seconds. Use `python cli.py analyze <ticker> --fresh` when you want to bypass that cache.

### GPU behavior

FinBERT startup tries to use CUDA only when the installed Torch build and the detected GPU are compatible. Otherwise the registry falls back to CPU automatically.

### Email summaries

To email summaries from scheduled runs, configure:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS`
- `SMTP_FROM`
- `EMAIL_TO`

Then run with:

```bash
python cli.py run --once --email-to ops@example.com
```

or rely on the default recipients from `EMAIL_TO`.

## Troubleshooting

### `Agent analysis unavailable`

Usually means:

- no LLM key is configured
- the configured provider rejected the model name
- the provider endpoint is unreachable

Check `LLM_PROVIDER` and the matching provider credentials first.

### No output in the viewer

Check that:

- you have already run `analyze` or `run --once`
- summaries exist under `output/analysis/`
- `ANALYSIS_DIR` points at that directory if you moved it

### Few or no documents ingested

The system can run with partial credentials, but coverage improves noticeably when you configure Finnhub, Reddit, and FRED.

### CUDA not used

Set `FINBERT_DEVICE=auto` unless you have a reason to force a mode. If the app still chooses CPU, the installed Torch build probably does not support the local GPU architecture.
