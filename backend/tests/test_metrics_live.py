"""Opt-in OS measurements, not deterministic fixture values."""

import os

import pytest

from app.metrics import MetricsCollector, MetricsResponse, Settings


@pytest.mark.skipif(
    os.environ.get("INFRAWATCH_RUN_LIVE_TESTS") != "1",
    reason="Enable explicit local OS measurements",
)
def test_local_system_real_metrics():
    settings = Settings.from_env()
    sample = MetricsCollector(settings).collect()
    assert not sample.errors
    MetricsResponse(
        status="ok",
        host=settings.host,
        collected_at=sample.collected_at,
        age_seconds=0.0,
        metrics=sample.values,
        errors=sample.errors,
    )
    assert sample.values.cpu.measurement_window_ms >= 900
    assert sample.values.memory.total_bytes > 0
    assert sample.values.disk.total_bytes > 0
