"""Agent-recoverable error type shared by every tool.

Tools raise ``ReviewToolError`` instead of returning ad-hoc error dictionaries.
The server converts it into an MCP error result (``isError: true``) whose text
always has the same four parts, so an agent can decide whether to fix its
arguments, narrow the request, or retry:

    [CODE] what went wrong. Hint: what to do next. Retryable: yes|no
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable, documented failure categories."""

    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_INVALID_RESPONSE = "UPSTREAM_INVALID_RESPONSE"


class ReviewToolError(Exception):
    """A failure the calling agent can act on. Never carries internal details."""

    def __init__(self, code: ErrorCode, message: str, hint: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = retryable

    def agent_message(self) -> str:
        """Render the one-line message shown to the agent."""
        retry = "yes" if self.retryable else "no"
        return f"[{self.code.value}] {self.message} Hint: {self.hint} Retryable: {retry}"
