"""Structured operational telemetry for MCP tool invocations.

The registry is deliberately process-local and dependency-free. It gives operators
useful health signals without collecting request arguments, FEMA records, or other
potentially sensitive content. Metrics reset whenever the process restarts.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any


class JsonLogFormatter(logging.Formatter):
    """Render one compact JSON object per log event for platform ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("tool_name", "request_id", "duration_ms", "outcome", "error_code"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configure this package's JSON logger without altering host-library logs."""
    package_logger = logging.getLogger("fema_oversight")
    if any(getattr(handler, "_fema_oversight_json", False) for handler in package_logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    handler._fema_oversight_json = True  # type: ignore[attr-defined]
    package_logger.addHandler(handler)
    package_logger.setLevel(level)
    package_logger.propagate = False


@dataclass
class ToolMetric:
    """Aggregate counters for one tool; no request content is retained."""

    invocations: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    @property
    def average_latency_ms(self) -> float:
        return round(self.total_latency_ms / self.invocations, 3) if self.invocations else 0.0


class TelemetryRegistry:
    """Thread-safe in-memory counters suitable for async and sync MCP tools."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = datetime.now(UTC).isoformat()
        self._tools: dict[str, ToolMetric] = {}

    def record(self, tool_name: str, duration_ms: float, *, succeeded: bool) -> None:
        with self._lock:
            metric = self._tools.setdefault(tool_name, ToolMetric())
            metric.invocations += 1
            metric.successes += int(succeeded)
            metric.failures += int(not succeeded)
            metric.total_latency_ms += duration_ms
            metric.max_latency_ms = max(metric.max_latency_ms, duration_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tools = {}
            for name, metric in sorted(self._tools.items()):
                data = asdict(metric)
                data["total_latency_ms"] = round(metric.total_latency_ms, 3)
                data["max_latency_ms"] = round(metric.max_latency_ms, 3)
                data["average_latency_ms"] = metric.average_latency_ms
                tools[name] = data
            return {
                "started_at": self._started_at,
                "privacy": "Aggregate process-local counters only; no inputs or FEMA records are retained.",
                "tools": tools,
            }


telemetry = TelemetryRegistry()


class InvocationTimer:
    """Small monotonic timer shared by sync and async tool wrappers."""

    def __init__(self) -> None:
        self._started = perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return round((perf_counter() - self._started) * 1000, 3)
