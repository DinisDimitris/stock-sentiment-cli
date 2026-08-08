"""
GitHub Models API client — OpenAI-compatible endpoint, free with Copilot Pro PAT.
Rate limits: ~15 req/min, ~150 req/day for GPT-4o-mini.
"""

from __future__ import annotations

import logging
import os

from config.settings import settings

logger = logging.getLogger(__name__)


def get_client():
    try:
        from openai import AsyncOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency 'openai'. Install project dependencies with "
            "'pip install -r requirements.txt' before running analysis."
        ) from exc

    api_key = settings.open_ai_api_key 
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured. Set it in .env or environment.")
    return AsyncOpenAI(
        api_key=api_key
    )
