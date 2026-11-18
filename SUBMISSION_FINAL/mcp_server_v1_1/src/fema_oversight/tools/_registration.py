"""Shared plumbing for publishing tools on FastMCP."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastmcp.exceptions import ToolError

from fema_oversight.errors import ReviewToolError

T = TypeVar("T")

READ_ONLY_EXTERNAL = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
READ_ONLY_LOCAL = {**READ_ONLY_EXTERNAL, "openWorldHint": False}


def agent_errors(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Convert ``ReviewToolError`` into an MCP error result the agent can act on.

    Any other exception is left to FastMCP, which is configured to mask its
    details so internal information never reaches the client.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return await func(*args, **kwargs)
        except ReviewToolError as exc:
            raise ToolError(exc.agent_message()) from None

    return wrapper
