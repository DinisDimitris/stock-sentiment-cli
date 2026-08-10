from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from ingestion import scheduler


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
