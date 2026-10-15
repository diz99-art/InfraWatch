"""Read-only, single-process system sampling; no request-triggered OS work."""

import asyncio
import logging
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Callable, Literal

import psutil
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

SAFE_INTEGER = 2**53 - 1
Count = Annotated[int, Field(strict=True, ge=0, le=SAFE_INTEGER)]
Total = Annotated[int, Field(strict=True, gt=0, le=SAFE_INTEGER)]
Percent = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
Resource = Literal["cpu", "memory", "disk", "uptime"]
RESOURCES = ("cpu", "memory", "disk", "uptime")
logger = logging.getLogger(__name__)


def utc_string(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def validate_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
            raise ValueError
    except ValueError:
        raise ValueError("Invalid UTC timestamp") from None
    return value


UTCString = Annotated[
    str,
    Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"),
    AfterValidator(validate_utc),
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Host(Model):
    id: str = Field(default="local", pattern=r"^[a-z0-9_-]{1,64}$")
    label: str = Field(default="Local system", min_length=1, max_length=80)
    platform: Literal["darwin", "linux", "win32", "other"] = "other"
    scope: Literal["local_system"] = "local_system"


class CPU(Model):
    usage_percent: Percent
    measurement_window_ms: Total


class Memory(Model):
    total_bytes: Total
    available_bytes: Count
    used_bytes: Count
    usage_percent: Percent

    @model_validator(mode="after")
    def coherent(self):
        if (
            self.available_bytes > self.total_bytes
            or self.used_bytes != self.total_bytes - self.available_bytes
            or abs(self.usage_percent - self.used_bytes / self.total_bytes * 100)
            > 0.051
        ):
            raise ValueError("Invalid memory values")
        return self


class Disk(Model):
    target_id: Literal["primary"] = "primary"
    total_bytes: Total
    used_bytes: Count
    free_bytes: Count
    usage_percent: Percent

    @model_validator(mode="after")
    def coherent(self):
        if max(self.used_bytes, self.free_bytes) > self.total_bytes:
            raise ValueError("Invalid disk values")
        return self


class Uptime(Model):
    seconds: Count
    booted_at: UTCString


class Values(Model):
    cpu: CPU | None
    memory: Memory | None
    disk: Disk | None
    uptime: Uptime | None


class CollectionError(Model):
    resource: Resource
    code: Literal["COLLECTION_FAILED", "INVALID_VALUE"]
    message: str


class MetricsResponse(Model):
    schema_version: Literal[1] = 1
    status: Literal["ok", "partial"]
    host: Host
    collected_at: UTCString
    age_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    collection_interval_seconds: Literal[5] = 5
    metrics: Values
    errors: tuple[CollectionError, ...]

    @model_validator(mode="after")
    def coherent(self):
        missing = {name for name in RESOURCES if getattr(self.metrics, name) is None}
        if (
            (
                self.metrics.uptime is not None
                and self.metrics.uptime.booted_at > self.collected_at
            )
            or len(missing) == 4
            or missing != {error.resource for error in self.errors}
            or len(missing) != len(self.errors)
            or self.status != ("partial" if missing else "ok")
        ):
            raise ValueError("Invalid metrics state")
        return self


@dataclass(frozen=True)
class Settings:
    host: Host
    disk_path: str

    @classmethod
    def from_env(cls):
        platform = (
            sys.platform if sys.platform in ("darwin", "linux", "win32") else "other"
        )
        try:
            host = Host(
                id=os.environ.get("INFRAWATCH_HOST_ID", "local"),
                label=os.environ.get("INFRAWATCH_HOST_LABEL", "Local system"),
                platform=platform,
            )
        except ValidationError:
            raise ValueError("Invalid public host alias configuration") from None
        default_path = (
            Path(os.environ.get("SystemRoot", sys.executable)).anchor
            if os.name == "nt"
            else "/"
        )
        path = os.environ.get("INFRAWATCH_DISK_PATH", default_path)
        if not Path(path).is_absolute():
            raise ValueError("Disk target must be an absolute local filesystem path")
        return cls(host, path)


@dataclass(frozen=True)
class Sample:
    values: Values
    errors: tuple[CollectionError, ...]
    collected_at: str


class MetricsCollector:
    def __init__(
        self, settings, provider=psutil, epoch=time.time, monotonic=time.monotonic
    ):
        self.settings = settings
        self.provider = provider
        self.epoch = epoch
        self.monotonic = monotonic

    def cpu(self):
        start = self.monotonic()
        value = self.provider.cpu_percent(interval=1.0, percpu=False)
        return CPU(
            usage_percent=value,
            measurement_window_ms=max(1, round((self.monotonic() - start) * 1000)),
        )

    def memory(self):
        raw = self.provider.virtual_memory()
        # Validate before arithmetic; do not coerce strings/bools or clamp values.
        total = TotalValidator(total_bytes=raw.total).total_bytes
        available = CountValidator(value=raw.available).value
        used = total - available
        return Memory(
            total_bytes=total,
            available_bytes=available,
            used_bytes=used,
            usage_percent=round(used / total * 100, 1),
        )

    def disk(self):
        raw = self.provider.disk_usage(self.settings.disk_path)
        return Disk(
            total_bytes=raw.total,
            used_bytes=raw.used,
            free_bytes=raw.free,
            usage_percent=raw.percent,
        )

    def uptime(self):
        boot = self.provider.boot_time()
        now = self.epoch()
        if isinstance(boot, bool) or not isinstance(boot, (float, int)):
            raise ValueError("Invalid boot time")
        if not math.isfinite(boot) or boot < 0 or boot > now:
            raise ValueError("Invalid boot time")
        return Uptime(seconds=math.floor(now - boot), booted_at=utc_string(boot))

    def collect(self):
        values = {}
        errors = []
        for name in RESOURCES:
            try:
                values[name] = getattr(self, name)()
            except (ValidationError, ValueError, OverflowError):
                values[name] = None
                errors.append(
                    CollectionError(
                        resource=name,
                        code="INVALID_VALUE",
                        message=f"{name.capitalize()} metrics unavailable",
                    )
                )
            except Exception:
                # OS/provider details can contain local paths or identifiers.
                values[name] = None
                errors.append(
                    CollectionError(
                        resource=name,
                        code="COLLECTION_FAILED",
                        message=f"{name.capitalize()} metrics unavailable",
                    )
                )
        return Sample(Values(**values), tuple(errors), utc_string(self.epoch()))


class TotalValidator(Model):
    total_bytes: Total


class CountValidator(Model):
    value: Count


class MetricsUnavailable(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class MetricsService:
    def __init__(
        self,
        settings: Settings | None = None,
        collector: Callable[[], Sample] | None = None,
        monotonic=time.monotonic,
        interval=5.0,
        deadline=3.0,
        stale_after=15.0,
    ):
        self.settings = settings or Settings.from_env()
        self.collect = collector or MetricsCollector(self.settings).collect
        self.monotonic = monotonic
        self.interval = interval
        self.deadline = deadline
        self.stale_after = stale_after
        self.sample = None
        self.completed_at = None
        self.failure = None
        self.task = None
        self.stop_event = None
        self.executor = None
        self.last_log = None
        self.last_log_at = -math.inf

    async def start(self):
        if self.task is not None:
            return
        self.sample = None
        self.completed_at = None
        self.failure = None
        self.stop_event = asyncio.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="metrics")
        self.task = asyncio.create_task(self._run(), name="metrics-sampler")

    async def stop(self):
        if self.task is None:
            return
        self.stop_event.set()
        task = self.task
        await task
        self.task = None
        self.sample = None
        self.completed_at = None

    def _log_state(self, code):
        now = self.monotonic()
        if code != self.last_log or now - self.last_log_at >= 30:
            if code:
                logger.warning("Metrics collection state: %s", code)
            self.last_log = code
            self.last_log_at = now

    async def _run(self):
        loop = asyncio.get_running_loop()
        next_start = self.monotonic()
        try:
            while not self.stop_event.is_set():
                future = loop.run_in_executor(self.executor, self.collect)
                done, _ = await asyncio.wait({future}, timeout=self.deadline)
                timed_out = not done
                if timed_out:
                    self.failure = "COLLECTION_TIMEOUT"
                    self._log_state(self.failure)
                try:
                    result = (
                        await future
                    )  # Drain before another submit, including after timeout.
                    if not timed_out and not self.stop_event.is_set():
                        self.sample = result
                        self.completed_at = self.monotonic()
                        self.failure = (
                            "COLLECTION_FAILED" if len(result.errors) == 4 else None
                        )
                        self._log_state(
                            self.failure or ("PARTIAL" if result.errors else None)
                        )
                except Exception:
                    self.failure = "COLLECTION_FAILED"
                    self._log_state(self.failure)
                next_start += self.interval
                now = self.monotonic()
                if next_start <= now:
                    next_start += (
                        math.floor((now - next_start) / self.interval) + 1
                    ) * self.interval
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(), timeout=next_start - now
                    )
                except TimeoutError:
                    pass
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None

    def response(self):
        if self.failure:
            raise MetricsUnavailable(self.failure)
        if self.sample is None or self.completed_at is None:
            raise MetricsUnavailable("METRICS_NOT_READY")
        age = self.monotonic() - self.completed_at
        if age >= self.stale_after:
            raise MetricsUnavailable("METRICS_STALE")
        return MetricsResponse(
            status="partial" if self.sample.errors else "ok",
            host=self.settings.host,
            collected_at=self.sample.collected_at,
            age_seconds=round(age, 1),
            metrics=self.sample.values,
            errors=self.sample.errors,
        )
