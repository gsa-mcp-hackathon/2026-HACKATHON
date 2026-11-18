"""Persistent application logs written to a Unity Catalog volume.

Databricks Apps only keep recent stdout/stderr, so this module also writes
log records as JSON lines to a UC volume (``LOG_VOLUME_PATH``). Volume files
cannot be appended to, so records are buffered in memory and each flush writes
a NEW small file:

    <LOG_VOLUME_PATH>/YYYY/MM/DD/<run_id>-<seq>.jsonl

Flushes happen every ``FLUSH_SECONDS``, when ``FLUSH_LINES`` records are
buffered, and at shutdown. Console logging is unchanged, so the Apps Logs tab
still works.

What is logged: HTTP requests (method, path without query string, status,
duration), MCP tool calls (tool name, outcome, duration), and any record at
INFO or above from the app's loggers. Never logged: request/response bodies,
query strings, tool arguments, headers, tokens, or user identities.

Failure posture: logging must never break the app. If the volume is not
configured or a write fails, the app keeps serving; failed batches are kept in
memory (bounded) and retried on the next flush, and a single warning per
failure streak goes to stderr.
"""

from __future__ import annotations

import atexit
import io
import json
import logging
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from starlette.middleware import Middleware as AsgiMiddleware

FLUSH_SECONDS = 30.0
FLUSH_LINES = 200
MAX_BUFFER_LINES = 10_000

# Noisy client libraries: keep only their warnings and errors. httpx/httpx2
# log full request URLs (query strings included) at INFO, so they stay quiet.
_QUIET_PREFIXES = ("databricks.sdk", "urllib3", "httpcore", "httpx")

# Loggers that set propagate=False and so would bypass the root handler.
_NON_PROPAGATING_LOGGERS = ("fastmcp", "fema_oversight.lancelot")

access_log = logging.getLogger("fema_oversight.access")
tool_log = logging.getLogger("fema_oversight.tools")

_local = threading.local()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JsonLineFormatter(logging.Formatter):
    """One JSON object per record. Structured fields go in ``extra={"event": {...}}``."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run_id": self.run_id,
        }
        event = getattr(record, "event", None)
        if isinstance(event, dict):
            entry.update(event)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class VolumeLogHandler(logging.Handler):
    """Buffer formatted records and periodically write them to a UC volume."""

    def __init__(self, base_path: str, run_id: str) -> None:
        super().__init__(level=logging.INFO)
        self.base_path = base_path.rstrip("/")
        self.run_id = run_id
        self.setFormatter(JsonLineFormatter(run_id))
        self._buf_lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._lines: list[str] = []
        self._dropped = 0
        self._seq = 0
        self._failing = False
        self._client: Any = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="volume-log-flusher", daemon=True
        )
        self._thread.start()

    # logging.Handler API -------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        # Drop records produced while uploading (SDK/urllib3) to avoid loops.
        if getattr(_local, "in_flush", False):
            return
        if record.name.startswith(_QUIET_PREFIXES) and record.levelno < logging.WARNING:
            return
        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with self._buf_lock:
            if len(self._lines) >= MAX_BUFFER_LINES:
                self._dropped += 1
                return
            self._lines.append(line)
            full = len(self._lines) >= FLUSH_LINES
        if full:
            self._wake.set()

    def flush(self) -> None:
        _local.in_flush = True
        try:
            with self._flush_lock:
                self._flush_once()
        finally:
            _local.in_flush = False

    def close(self) -> None:
        # logging.config.dictConfig() (run by uvicorn at server start) calls
        # close() on EVERY existing handler. Only flush here; the flusher keeps
        # running. The real stop happens in shutdown(), registered with atexit.
        self.flush()

    def shutdown(self) -> None:
        """Stop the flusher and write any remaining records (process exit)."""
        self._stop.set()
        self._wake.set()
        try:
            self.flush()
        finally:
            super().close()

    # internals -----------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(FLUSH_SECONDS)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.flush()
            except Exception:  # never let the flusher thread die
                pass

    def _get_client(self) -> Any:
        if self._client is None:
            # In Databricks Apps the SDK authenticates as the app's service
            # principal from the injected DATABRICKS_CLIENT_ID/SECRET.
            from databricks.sdk import WorkspaceClient

            self._client = WorkspaceClient()
        return self._client

    def _flush_once(self) -> None:
        with self._buf_lock:
            lines, self._lines = self._lines, []
            dropped, self._dropped = self._dropped, 0
        if dropped:
            lines.append(
                json.dumps(
                    {
                        "ts": _utc_now().isoformat(timespec="milliseconds"),
                        "level": "WARNING",
                        "logger": __name__,
                        "msg": f"log buffer full; dropped {dropped} records",
                        "run_id": self.run_id,
                    }
                )
            )
        if not lines:
            return
        now = _utc_now()
        self._seq += 1
        path = (
            f"{self.base_path}/{now:%Y/%m/%d}/"
            f"{self.run_id}-{self._seq:06d}.jsonl"
        )
        data = ("\n".join(lines) + "\n").encode("utf-8")
        try:
            self._get_client().files.upload(path, io.BytesIO(data), overwrite=False)
        except Exception as exc:
            # Keep the batch (newest records win if the cap is hit) and retry.
            with self._buf_lock:
                merged = lines + self._lines
                overflow = max(0, len(merged) - MAX_BUFFER_LINES)
                self._lines = merged[overflow:]
                self._dropped += overflow
            if not self._failing:
                self._failing = True
                sys.stderr.write(
                    f"[volume_log] WARNING: could not write logs to {self.base_path}: "
                    f"{type(exc).__name__}: {str(exc)[:300]}. Will retry.\n"
                )
            return
        if self._failing:
            self._failing = False
            sys.stderr.write(f"[volume_log] log writes to {self.base_path} recovered.\n")


class AccessLogMiddleware:
    """Pure-ASGI access log (safe for streaming MCP responses)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: dict) -> None:
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status", 500)
            await send(message)

        path = scope.get("path", "")
        method = scope.get("method", "")
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            access_log.exception(
                "%s %s raised",
                method,
                path,
                extra={"event": {"kind": "http", "method": method, "path": path}},
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            # Health checks are frequent and uninteresting: DEBUG (not kept).
            level = logging.DEBUG if path == "/health" else logging.INFO
            access_log.log(
                level,
                "%s %s %s %.1fms",
                method,
                path,
                status["code"],
                duration_ms,
                extra={
                    "event": {
                        "kind": "http",
                        "method": method,
                        "path": path,
                        "status": status["code"],
                        "duration_ms": duration_ms,
                    }
                },
            )


class ToolCallLogMiddleware(Middleware):
    """Log each MCP tool call: name, outcome, duration. Arguments are NOT logged."""

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        name = getattr(context.message, "name", "?")
        start = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            tool_log.warning(
                "tool %s failed after %.1fms: %s",
                name,
                duration_ms,
                type(exc).__name__,
                extra={
                    "event": {
                        "kind": "tool_call",
                        "tool": name,
                        "ok": False,
                        "error": type(exc).__name__,
                        "duration_ms": duration_ms,
                    }
                },
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        tool_log.info(
            "tool %s ok %.1fms",
            name,
            duration_ms,
            extra={
                "event": {
                    "kind": "tool_call",
                    "tool": name,
                    "ok": True,
                    "duration_ms": duration_ms,
                }
            },
        )
        return result


_handler: VolumeLogHandler | None = None


def setup_logging(mcp: FastMCP, volume_path: str | None) -> list[AsgiMiddleware]:
    """Configure console + volume logging; return ASGI middleware for ``mcp.run``.

    Safe to call once at startup. With no ``volume_path`` only console logging
    and the access/tool logs are enabled.
    """
    global _handler
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Keep console output as before for HTTP client libraries (URL logging).
    for name in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if not root.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(console)

    if volume_path and _handler is None:
        run_id = f"{_utc_now():%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
        _handler = VolumeLogHandler(volume_path, run_id)
        root.addHandler(_handler)
        # Some loggers do not propagate to root (FastMCP's own logger, and the
        # Lancelot client, which prints one result line per call: tool, runId,
        # status, isError, errorCode, elapsed). Attach the volume handler to
        # them directly so those lines are kept too.
        for name in _NON_PROPAGATING_LOGGERS:
            lg = logging.getLogger(name)
            if not lg.propagate and _handler not in lg.handlers:
                lg.addHandler(_handler)
        atexit.register(_handler.shutdown)
        logging.getLogger(__name__).info(
            "volume logging enabled",
            extra={
                "event": {
                    "kind": "startup",
                    "volume_path": volume_path,
                    "app_name": os.getenv("DATABRICKS_APP_NAME", ""),
                }
            },
        )

    mcp.add_middleware(ToolCallLogMiddleware())
    return [AsgiMiddleware(AccessLogMiddleware)]
