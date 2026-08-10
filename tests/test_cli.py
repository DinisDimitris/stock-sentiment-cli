import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

import cli


def test_run_accepts_log_file_and_writes_logs(tmp_path):
    log_path = tmp_path / "stock-sentiment.log"

    async def fake_run_once(*args, **kwargs):
        logging.getLogger("cli").info("run loop started")

    runner = CliRunner()
    with patch("cli._run_once", new=fake_run_once):
        result = runner.invoke(cli.cli, ["run", "--once", "--log-file", str(log_path)])

    assert result.exit_code == 0, result.output
    assert log_path.exists()
    assert "run loop started" in log_path.read_text()


@pytest.mark.parametrize(
    ("interval", "expected_minutes"),
    [
        ("15m", 15),
        ("1h", 60),
        ("daily", 24 * 60),
        ("weekly", 7 * 24 * 60),
        ("2 weeks", 14 * 24 * 60),
    ],
)
def test_parse_interval_to_minutes(interval, expected_minutes):
    assert cli.parse_interval_to_minutes(interval) == expected_minutes


def test_run_accepts_interval_and_passes_it_to_daemon():
    runner = CliRunner()
    fake_run_daemon = AsyncMock(return_value=None)

    with patch("cli._run_daemon", new=fake_run_daemon):
        result = runner.invoke(cli.cli, ["run", "--interval", "2weeks"])

    assert result.exit_code == 0, result.output
    assert fake_run_daemon.await_count == 1
    assert fake_run_daemon.await_args.kwargs["interval_minutes"] == 14 * 24 * 60
    assert fake_run_daemon.await_args.kwargs["run_analysis"] is True


def test_run_accepts_email_recipient_option():
    runner = CliRunner()
    fake_run_daemon = AsyncMock(return_value=None)

    with patch("cli._run_daemon", new=fake_run_daemon):
        result = runner.invoke(cli.cli, ["run", "--email-to", "ops@example.com"])

    assert result.exit_code == 0, result.output
    assert fake_run_daemon.await_count == 1
    assert fake_run_daemon.await_args.kwargs["email_tos"] == ("ops@example.com",)
    assert fake_run_daemon.await_args.kwargs["run_analysis"] is True


def test_run_can_disable_analysis():
    runner = CliRunner()
    fake_run_daemon = AsyncMock(return_value=None)

    with patch("cli._run_daemon", new=fake_run_daemon):
        result = runner.invoke(cli.cli, ["run", "--no-analysis"])

    assert result.exit_code == 0, result.output
    assert fake_run_daemon.await_count == 1
    assert fake_run_daemon.await_args.kwargs["run_analysis"] is False


def test_run_once_can_disable_analysis():
    runner = CliRunner()
    fake_run_once = AsyncMock(return_value=None)

    with patch("cli._run_once", new=fake_run_once):
        result = runner.invoke(cli.cli, ["run", "--once", "--no-analysis"])

    assert result.exit_code == 0, result.output
    assert fake_run_once.await_count == 1
    assert fake_run_once.await_args.kwargs["run_analysis"] is False


def test_inspect_company_outputs_json_payloads():
    runner = CliRunner()
    sample_documents = [{
        "id": 42,
        "ticker": "AAPL",
        "source": "news",
        "source_subtype": "article",
        "title": "Apple announces new hardware",
        "body": "A body",
        "published_at": "2026-08-10T00:00:00+00:00",
        "retrieved_at": "2026-08-10T00:00:00+00:00",
        "raw_json": {"score": 7, "url": "https://example.com/1"},
    }]

    with patch("cli._inspect_company", new=AsyncMock(return_value=sample_documents)):
        result = runner.invoke(cli.cli, ["inspect", "Apple", "--limit", "1"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["source"] == "news"
    assert payload[0]["raw_json"]["score"] == 7


def test_inspect_company_can_use_text_mode():
    runner = CliRunner()
    sample_documents = [{
        "id": 7,
        "ticker": "MSFT",
        "source": "social",
        "source_subtype": "post",
        "title": "Microsoft update",
        "body": "A post",
        "published_at": None,
        "retrieved_at": None,
        "raw_json": {"score": 3},
    }]

    with patch("cli._inspect_company", new=AsyncMock(return_value=sample_documents)):
        result = runner.invoke(cli.cli, ["inspect", "MSFT", "--text"])

    assert result.exit_code == 0, result.output
    assert "Microsoft update" in result.output
    assert "social" in result.output
