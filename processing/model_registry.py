"""
FinBERT model registry. Loads all four model variants once at startup.
All inference is in-process — no HTTP microservice.
Memory requirement: ~420MB per model, ~1.7GB total (CPU).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy-loaded pipelines — populated by load_models()
_registry: dict[str, Any] = {}


def load_models() -> None:
    """Call once at startup before any inference."""
    try:
        from transformers import pipeline
    except ImportError:
        logger.error("transformers not installed — sentiment scoring unavailable")
        return

    model_configs = {
        "finbert_general": "ProsusAI/finbert",
        "finbert_tone": "yiyanghkust/finbert-tone",
        "finbert_fls": "yiyanghkust/finbert-fls",
        "finbert_esg": "yiyanghkust/finbert-esg",
    }

    for key, model_id in model_configs.items():
        logger.info("[model_registry] Loading %s ...", model_id)
        try:
            _registry[key] = pipeline(
                "text-classification",
                model=model_id,
                top_k=None,
                truncation=True,
                max_length=512,
            )
            logger.info("[model_registry] %s ready.", key)
        except Exception as exc:
            logger.error("[model_registry] Failed to load %s: %s", model_id, exc)


def get_model(key: str) -> Any:
    if key not in _registry:
        raise RuntimeError(f"Model '{key}' not loaded. Call load_models() first.")
    return _registry[key]


def is_ready() -> bool:
    return bool(_registry)
