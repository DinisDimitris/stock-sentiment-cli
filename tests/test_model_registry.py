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
        report = model_registry.load_models()

    assert fake_pipeline.call_count == 4
    assert all(call.kwargs["device"] == -1 for call in fake_pipeline.call_args_list)
    assert set(model_registry._registry) == {
        "finbert_general",
        "finbert_tone",
        "finbert_fls",
        "finbert_esg",
    }
    assert report["device"] == "cpu"
    assert report["total"] == 4
    assert len(report["loaded"]) == 4
    assert len(report["failed"]) == 0


def test_load_models_reports_partial_failures(monkeypatch):
    def fake_pipeline(*args, **kwargs):
        model_id = kwargs["model"]
        if model_id == "yiyanghkust/finbert-tone":
            raise ValueError("missing model_type")
        return "pipeline"

    fake_transformers = SimpleNamespace(pipeline=fake_pipeline)
    monkeypatch.delenv("FINBERT_DEVICE", raising=False)
    monkeypatch.setattr(model_registry, "_select_pipeline_device", lambda: -1)

    with patch.dict(sys.modules, {"transformers": fake_transformers}):
        report = model_registry.load_models()

    assert report["total"] == 4
    assert len(report["loaded"]) == 3
    assert len(report["failed"]) == 1
    assert report["failed"][0]["key"] == "finbert_tone"
    assert "missing model_type" in report["failed"][0]["error"]

    lines = model_registry.format_startup_health_report(report)
    assert lines[0].startswith("[health] Model startup probe: loaded 3/4")
    assert any("Failed models:" in line for line in lines)
