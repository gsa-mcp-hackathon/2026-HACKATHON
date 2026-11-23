"""Shared plumbing for publishing tools on FastMCP."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import uuid4

from fastmcp.exceptions import ToolError

from fema_oversight.errors import ReviewToolError
from fema_oversight.observability import InvocationTimer, telemetry

T = TypeVar("T")
logger = logging.getLogger("fema_oversight.tools")

READ_ONLY_EXTERNAL = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
READ_ONLY_LOCAL = {**READ_ONLY_EXTERNAL, "openWorldHint": False}


def agent_errors(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Instrument an async tool and translate agent-recoverable failures.

    Unexpected exceptions remain masked by FastMCP. Logs contain the exception
    class but never tool inputs, returned records, URLs, headers, or stack traces.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        request_id = uuid4().hex
        timer = InvocationTimer()
        try:
            result = await func(*args, **kwargs)
        except ReviewToolError as exc:
            _record(func.__name__, request_id, timer, succeeded=False, error_code=exc.code.value)
            raise ToolError(exc.agent_message()) from None
        except Exception as exc:
            _record(func.__name__, request_id, timer, succeeded=False, error_code=type(exc).__name__)
            raise
        _record(func.__name__, request_id, timer, succeeded=True)
        return result

    return wrapper


def observe_sync(func: Callable[..., T]) -> Callable[..., T]:
    """Instrument a synchronous local tool without retaining its arguments."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        request_id = uuid4().hex
        timer = InvocationTimer()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            _record(func.__name__, request_id, timer, succeeded=False, error_code=type(exc).__name__)
            raise
        _record(func.__name__, request_id, timer, succeeded=True)
        return result

    return wrapper


def _record(
    tool_name: str,
    request_id: str,
    timer: InvocationTimer,
    *,
    succeeded: bool,
    error_code: str | None = None,
) -> None:
    """Update aggregate metrics and emit one content-free structured event."""
    duration_ms = timer.elapsed_ms
    telemetry.record(tool_name, duration_ms, succeeded=succeeded)
    outcome = "success" if succeeded else "failure"
    log = logger.info if succeeded else logger.warning
    log(
        "tool invocation completed",
        extra={
            "tool_name": tool_name,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "outcome": outcome,
            "error_code": error_code,
        },
    )
