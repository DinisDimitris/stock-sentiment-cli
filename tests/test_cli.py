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


def test_run_accepts_email_recipient_option():
    runner = CliRunner()
    fake_run_daemon = AsyncMock(return_value=None)

    with patch("cli._run_daemon", new=fake_run_daemon):
        result = runner.invoke(cli.cli, ["run", "--email-to", "ops@example.com"])

    assert result.exit_code == 0, result.output
    assert fake_run_daemon.await_count == 1
    assert fake_run_daemon.await_args.kwargs["email_tos"] == ("ops@example.com",)
