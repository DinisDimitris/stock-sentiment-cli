"""
GitHub Models API client — OpenAI-compatible endpoint, free with Copilot Pro PAT.
Rate limits: ~15 req/min, ~150 req/day for GPT-4o-mini.
"""

from __future__ import annotations

import logging
import os

from openai import AsyncOpenAI

from config.settings import settings

logger = logging.getLogger(__name__)


def get_client() -> AsyncOpenAI:
    pat = settings.github_pat or os.environ.get("GITHUB_PAT", "")
    if not pat:
        raise RuntimeError("GITHUB_PAT not configured. Set it in .env or environment.")
    return AsyncOpenAI(
        base_url=settings.github_models_endpoint,
        api_key=pat,
    )
