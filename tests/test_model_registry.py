from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import processing.model_registry as model_registry


@pytest.fixture(autouse=True)
def clear_registry():
    model_registry._registry.clear()
    yield
    model_registry._registry.clear()


def test_select_pipeline_device_uses_cpu_when_cuda_arch_is_unsupported(monkeypatch):
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            get_arch_list=lambda: ["sm_75", "sm_80", "sm_86"],
        )
    )

    monkeypatch.delenv("FINBERT_DEVICE", raising=False)
    monkeypatch.setattr(model_registry, "_read_gpu_compute_capability", lambda: (6, 1))

    assert model_registry._select_pipeline_device(fake_torch) == -1


def test_select_pipeline_device_uses_cuda_when_arch_is_supported(monkeypatch):
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            get_arch_list=lambda: ["sm_75", "sm_80", "sm_86"],
        )
    )

    monkeypatch.delenv("FINBERT_DEVICE", raising=False)
    monkeypatch.setattr(model_registry, "_read_gpu_compute_capability", lambda: (7, 5))

    assert model_registry._select_pipeline_device(fake_torch) == 0


def test_load_models_passes_selected_device_to_transformers_pipeline(monkeypatch):
    fake_pipeline = Mock(return_value="pipeline")
    fake_transformers = SimpleNamespace(pipeline=fake_pipeline)

    monkeypatch.delenv("FINBERT_DEVICE", raising=False)
    monkeypatch.setattr(model_registry, "_select_pipeline_device", lambda: -1)
    model_registry._registry.clear()

    with patch.dict(sys.modules, {"transformers": fake_transformers}):
        model_registry.load_models()

    assert fake_pipeline.call_count == 4
    assert all(call.kwargs["device"] == -1 for call in fake_pipeline.call_args_list)
    assert set(model_registry._registry) == {
        "finbert_general",
        "finbert_tone",
        "finbert_fls",
        "finbert_esg",
    }
