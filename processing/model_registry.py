"""
FinBERT model registry. Loads all four model variants once at startup.
All inference is in-process — no HTTP microservice.
Memory requirement: ~420MB per model, ~1.7GB total (CPU).
"""

from __future__ import annotations

import os
import logging
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Lazy-loaded pipelines — populated by load_models()
_registry: dict[str, Any] = {}


def _read_gpu_compute_capability() -> tuple[int, int] | None:
    """Read the first NVIDIA GPU compute capability without touching Torch CUDA."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return None

    first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    match = re.fullmatch(r"(\d+)\.(\d+)", first_line)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _select_pipeline_device(torch_module: Any | None = None) -> int:
    """
    Pick the best pipeline device for the current host.

    Returns:
        0 for CUDA, -1 for CPU.
    """
    requested = os.getenv("FINBERT_DEVICE", "auto").strip().lower()
    if requested in {"cpu", "-1"}:
        logger.info("[model_registry] FINBERT_DEVICE=%s -> using CPU", requested)
        return -1
    if requested in {"cuda", "gpu", "0"}:
        logger.info("[model_registry] FINBERT_DEVICE=%s -> forcing CUDA", requested)
        return 0
    if requested not in {"", "auto"}:
        logger.warning("[model_registry] Unknown FINBERT_DEVICE=%r; using auto detection", requested)

    if torch_module is None:
        try:
            import torch as torch_module  # type: ignore[no-redef]
        except ImportError:
            logger.info("[model_registry] torch not installed; using CPU")
            return -1

    cuda = getattr(torch_module, "cuda", None)
    if cuda is None:
        return -1

    try:
        capability = _read_gpu_compute_capability()
        if capability is None:
            logger.info("[model_registry] No NVIDIA GPU capability detected; using CPU")
            return -1

        device_arch = f"sm_{capability[0]}{capability[1]}"
        supported_arches = {
            arch.strip().lower()
            for arch in getattr(cuda, "get_arch_list", lambda: [])()
            if arch.strip().lower().startswith("sm_")
        }

        if not supported_arches:
            logger.info("[model_registry] Installed torch build does not expose CUDA arch support; using CPU")
            return -1

        if device_arch not in supported_arches:
            logger.warning(
                "[model_registry] CUDA device %s is not supported by the installed torch build; using CPU",
                device_arch,
            )
            return -1
    except (AssertionError, AttributeError, RuntimeError, ValueError) as exc:
        logger.warning("[model_registry] Could not verify CUDA compatibility (%s); using CPU", exc)
        return -1

    logger.info("[model_registry] Using CUDA device 0 for FinBERT")
    return 0


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
    device = _select_pipeline_device()

    for key, model_id in model_configs.items():
        logger.info("[model_registry] Loading %s ...", model_id)
        try:
            _registry[key] = pipeline(
                "text-classification",
                model=model_id,
                device=device,
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
