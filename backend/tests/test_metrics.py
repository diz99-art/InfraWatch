import asyncio
import math
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.metrics import (
    CPU,
    Disk,
    Host,
    Memory,
    MetricsCollector,
    MetricsResponse,
    MetricsService,
    MetricsUnavailable,
    Settings,
)


@pytest.fixture
def settings():
    return Settings(Host(id="local", label="Local system", platform="darwin"), "/")


@pytest.fixture
def provider():
    p = Mock()
    p.cpu_percent.return_value = 25.0
    p.virtual_memory.return_value = SimpleNamespace(total=1000, available=600)
    p.disk_usage.return_value = SimpleNamespace(
        total=1000, used=500, free=400, percent=55.6
    )
    p.boot_time.return_value = 1000.0
    return p


def collect(settings, provider):
    return MetricsCollector(
        settings, provider, epoch=lambda: 4600.0, monotonic=lambda: 10.0
    ).collect()


def test_normal_collection_definitions_and_privacy(settings, provider):
    sample = collect(settings, provider)
    assert sample.values.cpu.usage_percent == 25.0
    assert sample.values.memory.used_bytes == 400
    assert sample.values.memory.usage_percent == 40.0
    assert sample.values.disk.usage_percent == 55.6  # Not used/total.
    assert sample.values.uptime.seconds == 3600
    assert sample.collected_at == "1970-01-01T01:16:40.000Z"
    assert sample.errors == ()
    provider.cpu_percent.assert_called_once_with(interval=1.0, percpu=False)
    provider.disk_usage.assert_called_once_with("/")


@pytest.mark.parametrize(
    "resource,method",
    [
        ("cpu", "cpu_percent"),
        ("memory", "virtual_memory"),
        ("disk", "disk_usage"),
        ("uptime", "boot_time"),
    ],
)
def test_resource_failure_does_not_destroy_other_values(
    settings, provider, resource, method
):
    getattr(provider, method).side_effect = OSError("private-path-and-user")
    sample = collect(settings, provider)
    assert getattr(sample.values, resource) is None
    assert len(sample.errors) == 1
    assert sample.errors[0].code == "COLLECTION_FAILED"
    assert resource == sample.errors[0].resource
    assert "private" not in str(sample)
    assert sum(value is not None for value in sample.values.model_dump().values()) == 3


def test_all_collection_failures(settings, provider):
    for name in ["cpu_percent", "virtual_memory", "disk_usage", "boot_time"]:
        getattr(provider, name).side_effect = RuntimeError("sensitive")
    sample = collect(settings, provider)
    assert len(sample.errors) == 4
    assert all(value is None for value in sample.values.model_dump().values())


@pytest.mark.parametrize("bad", [-1.0, 100.1, math.nan, math.inf, "25", True])
def test_invalid_cpu_is_not_clamped(settings, provider, bad):
    provider.cpu_percent.return_value = bad
    sample = collect(settings, provider)
    assert sample.values.cpu is None
    assert sample.errors[0].code == "INVALID_VALUE"


@pytest.mark.parametrize("percent", [0.0, 100.0])
def test_percentage_boundaries(settings, provider, percent):
    provider.cpu_percent.return_value = percent
    provider.virtual_memory.return_value = SimpleNamespace(
        total=1000, available=1000 if percent == 0 else 0
    )
    provider.disk_usage.return_value = SimpleNamespace(
        total=1000,
        used=0 if percent == 0 else 1000,
        free=1000 if percent == 0 else 0,
        percent=percent,
    )
    sample = collect(settings, provider)
    assert sample.errors == ()
    assert (
        sample.values.cpu.usage_percent
        == sample.values.memory.usage_percent
        == sample.values.disk.usage_percent
        == percent
    )


@pytest.mark.parametrize(
    "total,available",
    [(0, 0), (-1, 0), (1000, 1001), (True, 0), (2**53, 0), (1000, "600")],
)
def test_invalid_memory(settings, provider, total, available):
    provider.virtual_memory.return_value = SimpleNamespace(
        total=total, available=available
    )
    sample = collect(settings, provider)
    assert sample.values.memory is None
    assert sample.errors[0].code == "INVALID_VALUE"


@pytest.mark.parametrize("boot", [-1, 4601, math.nan, True, "1000"])
def test_invalid_boot_time(settings, provider, boot):
    provider.boot_time.return_value = boot
    assert collect(settings, provider).values.uptime is None


def test_disk_path_failure_and_validation(settings, provider):
    provider.disk_usage.side_effect = PermissionError("private disk path")
    assert collect(settings, provider).errors[0].resource == "disk"
    with pytest.raises(ValidationError):
        Disk(total_bytes=1000, used_bytes=1001, free_bytes=0, usage_percent=100.0)
    with pytest.raises(ValidationError):
        Memory(
            total_bytes=1000, available_bytes=600, used_bytes=500, usage_percent=50.0
        )
    with pytest.raises(ValidationError):
        CPU(usage_percent=0.0, measurement_window_ms=0)


def test_configuration_safe_defaults_and_invalid_settings(monkeypatch):
    for key in ["INFRAWATCH_HOST_ID", "INFRAWATCH_HOST_LABEL", "INFRAWATCH_DISK_PATH"]:
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.host.id == "local"
    assert settings.host.label == "Local system"
    assert set(settings.host.model_dump()) == {"id", "label", "platform", "scope"}
    monkeypatch.setenv("INFRAWATCH_DISK_PATH", "relative")
    with pytest.raises(ValueError, match="absolute"):
        Settings.from_env()
    monkeypatch.setenv("INFRAWATCH_DISK_PATH", "/")
    monkeypatch.setenv("INFRAWATCH_HOST_ID", "private.invalid")
    with pytest.raises(ValueError, match="public host alias") as exc:
        Settings.from_env()
    assert "private.invalid" not in str(exc.value)


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def populated_service(settings, provider, clock=None):
    clock = clock or Clock()
    service = MetricsService(settings, monotonic=clock)
    service.sample = collect(settings, provider)
    service.completed_at = 0.0
    return service


def test_snapshot_age_and_stale_boundary(settings, provider):
    clock = Clock()
    service = populated_service(settings, provider, clock)
    clock.now = 14.9
    assert service.response().age_seconds == 14.9
    clock.now = 15.0
    with pytest.raises(MetricsUnavailable) as exc:
        service.response()
    assert exc.value.reason == "METRICS_STALE"


@pytest.mark.parametrize(
    "reason",
    ["METRICS_NOT_READY", "COLLECTION_FAILED", "COLLECTION_TIMEOUT", "METRICS_STALE"],
)
def test_metrics_503_headers_and_health_independence(settings, provider, reason):
    service = populated_service(settings, provider)
    if reason == "METRICS_NOT_READY":
        service.sample = None
    else:
        service.failure = reason

    async def noop():
        pass

    service.start = noop
    service.stop = noop
    with TestClient(create_app(service)) as client:
        response = client.get("/api/metrics")
        assert response.status_code == 503
        assert response.json()["error"] == {
            "code": 503,
            "message": "Metrics unavailable",
            "reason": reason,
            "retryable": True,
        }
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["retry-after"] == "5"
        assert client.get("/api/health").json() == {
            "status": "ok",
            "service": "InfraWatch",
        }


@pytest.mark.parametrize("partial", [False, True])
def test_api_schema_cached_reads_and_app_isolation(settings, provider, partial):
    if partial:
        provider.disk_usage.side_effect = OSError("private")
    service = populated_service(settings, provider)

    async def noop():
        pass

    service.start = noop
    service.stop = noop
    with TestClient(create_app(service)) as client:
        for _ in range(3):
            r = client.get("/api/metrics")
            assert r.status_code == 200
            assert r.json()["status"] == ("partial" if partial else "ok")
            assert r.headers["cache-control"] == "no-store"
            MetricsResponse.model_validate_json(r.content)
    provider.cpu_percent.assert_called_once()
    assert create_app().state.metrics_service is not create_app().state.metrics_service


def test_internal_api_error_hides_response_and_log_details(settings, caplog):
    service = MetricsService(settings)

    async def noop():
        pass

    service.start = noop
    service.stop = noop
    service.response = Mock(side_effect=RuntimeError("private-user-path"))
    with TestClient(create_app(service), raise_server_exceptions=False) as client:
        r = client.get("/api/metrics")
        assert r.status_code == 500
        assert r.json() == {"error": {"code": 500, "message": "Internal server error"}}
    assert "private-user-path" not in caplog.text


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


def test_service_start_stop_duplicate_and_snapshot_updates(settings, provider):
    async def scenario():
        calls = []

        def collector():
            calls.append(1)
            return collect(settings, provider)

        service = MetricsService(settings, collector=collector, interval=0.02)
        await service.start()
        original = service.task
        await service.start()
        assert service.task is original
        await eventually(lambda: service.completed_at is not None)
        first = service.completed_at
        await eventually(lambda: service.completed_at > first)
        assert len(calls) >= 2
        await service.stop()
        assert service.task is None and service.executor is None
        assert service.sample is None
        await service.stop()
        count = len(calls)
        await asyncio.sleep(0.03)
        assert count == len(calls)

    asyncio.run(scenario())


def test_service_timeout_no_overlap_late_result_discard_and_stop_drain(
    settings, provider
):
    async def scenario():
        gate = threading.Event()
        calls = []

        def collector():
            calls.append(1)
            assert gate.wait(2)
            return collect(settings, provider)

        service = MetricsService(
            settings, collector=collector, deadline=0.01, interval=0.02
        )
        await service.start()
        await eventually(lambda: service.failure == "COLLECTION_TIMEOUT")
        await asyncio.sleep(0.04)
        assert len(calls) == 1 and service.sample is None
        stopping = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        assert not stopping.done()
        gate.set()
        await stopping
        assert service.sample is None and service.executor is None

    asyncio.run(scenario())


def test_service_timeout_late_result_never_published(settings, provider):
    async def scenario():
        gate = threading.Event()
        finished = threading.Event()

        def collector():
            assert gate.wait(2)
            finished.set()
            return collect(settings, provider)

        service = MetricsService(settings, collector=collector, deadline=0.01)
        await service.start()
        await eventually(lambda: service.failure == "COLLECTION_TIMEOUT")
        gate.set()
        await eventually(finished.is_set)
        await asyncio.sleep(0.01)
        assert service.sample is None
        with pytest.raises(MetricsUnavailable) as exc:
            service.response()
        assert exc.value.reason == "COLLECTION_TIMEOUT"
        await service.stop()

    asyncio.run(scenario())


def test_service_collection_failure_recovers_without_api_crash(settings, provider):
    async def scenario():
        calls = 0

        def collector():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("private")
            return collect(settings, provider)

        service = MetricsService(settings, collector=collector, interval=0.02)
        await service.start()
        await eventually(lambda: service.failure == "COLLECTION_FAILED")
        await eventually(lambda: service.sample is not None)
        assert service.response().status == "ok"
        await service.stop()

    asyncio.run(scenario())


def test_lifespan_manages_service(settings, provider):
    service = MetricsService(settings, collector=lambda: collect(settings, provider))
    with TestClient(create_app(service)) as client:
        assert service.task is not None
        assert client.get("/api/health").status_code == 200
    assert service.task is None and service.executor is None


def test_cpu_measured_window_uses_monotonic(settings, provider):
    ticks = iter([0.0, 1.002])
    collector = MetricsCollector(settings, provider, monotonic=lambda: next(ticks))
    assert collector.cpu().measurement_window_ms == 1002


def test_invalid_timestamp_contract_is_rejected(settings, provider):
    service = populated_service(settings, provider)
    data = service.response().model_dump()
    data["collected_at"] = "2026-02-31T00:00:00.000Z"
    with pytest.raises(ValidationError):
        MetricsResponse.model_validate(data)
    data = service.response().model_dump()
    data["metrics"]["uptime"]["booted_at"] = "2099-01-01T00:00:00.000Z"
    with pytest.raises(ValidationError):
        MetricsResponse.model_validate(data)


def test_health_available_while_first_collection_is_pending(settings, provider):
    gate = threading.Event()

    def collector():
        assert gate.wait(2)
        return collect(settings, provider)

    service = MetricsService(settings, collector=collector)
    with TestClient(create_app(service)) as client:
        try:
            assert client.get("/api/health").status_code == 200
            r = client.get("/api/metrics")
            assert r.status_code == 503
            assert r.json()["error"]["reason"] == "METRICS_NOT_READY"
        finally:
            gate.set()
    assert service.task is None


def test_service_all_failed_snapshot_recovers_to_partial(settings, provider):
    async def scenario():
        count = 0

        def collector():
            nonlocal count
            count += 1
            if count == 1:
                for name in [
                    "cpu_percent",
                    "virtual_memory",
                    "disk_usage",
                    "boot_time",
                ]:
                    getattr(provider, name).side_effect = OSError("private")
            else:
                for name in ["cpu_percent", "virtual_memory", "boot_time"]:
                    getattr(provider, name).side_effect = None
            return collect(settings, provider)

        service = MetricsService(settings, collector=collector, interval=0.02)
        await service.start()
        await eventually(lambda: service.failure == "COLLECTION_FAILED")
        await eventually(lambda: service.failure is None)
        assert service.response().status == "partial"
        assert service.response().metrics.disk is None
        await service.stop()

    asyncio.run(scenario())
