from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from ingestion import scheduler


def test_run_analysis_cycle_forces_fresh_review_for_each_ticker():
    async def run():
        with (
            patch.object(scheduler, "_get_watched_tickers", new=AsyncMock(return_value=["NVDA"])),
            patch.object(scheduler, "run_review", new=AsyncMock(return_value={"ticker": "NVDA", "summary": "ok"})),
            patch.object(scheduler, "write_analysis_output", new=MagicMock()),
            patch.object(scheduler, "format_summary_text", new=MagicMock(return_value="summary text")),
        ):
            await scheduler._run_analysis_cycle(output_callback=lambda text: None)
            scheduler.run_review.assert_awaited_once_with("NVDA", force_refresh=True)

    asyncio.run(run())


def test_run_ingestion_cycle_can_skip_analysis():
    async def run():
        with (
            patch.object(scheduler, "_run_fast_sources", new=AsyncMock()),
            patch.object(scheduler, "_run_slow_sources", new=AsyncMock()),
            patch.object(scheduler, "_run_analysis_cycle", new=AsyncMock()),
        ):
            await scheduler._run_ingestion_cycle(run_analysis=False)
            scheduler._run_analysis_cycle.assert_not_awaited()

    asyncio.run(run())
