import logging
from unittest.mock import patch

from click.testing import CliRunner

import cli


def test_run_accepts_log_file_and_writes_logs(tmp_path):
    log_path = tmp_path / "stock-sentiment.log"

    async def fake_run_once():
        logging.getLogger("cli").info("run loop started")

    runner = CliRunner()
    with patch("cli._run_once", new=fake_run_once):
        result = runner.invoke(cli.cli, ["run", "--once", "--log-file", str(log_path)])

    assert result.exit_code == 0, result.output
    assert log_path.exists()
    assert "run loop started" in log_path.read_text()
