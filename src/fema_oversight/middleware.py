"""FastMCP middleware: structured errors and rate limiting.

The hackathon rubric emphasizes stable, agent-recoverable failures rather than
raw stack traces. FastMCP already validates against tool schemas, but its default
surface is aimed at developers. This middleware turns both validation failures
and runtime exceptions into compact, actionable JSON for an LLM agent.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from pydantic import ValidationError

from fema_oversight.clients import UpstreamServiceError
from fema_oversight.config import settings
from fema_oversight.models import ToolErrorResponse
from fema_oversight.security import stable_session_key

# How far to walk ``__cause__`` / ``__context__``. FastMCP wraps tool and
# argument errors one or two levels deep; a small bound avoids pathological
# self-referencing chains.
_MAX_CAUSE_DEPTH = 6

logger = logging.getLogger(__name__)

# Bucket key for the process-wide ceiling; cannot collide with session keys,
# which are always prefixed "session:".
_GLOBAL_BUCKET = "global"
_WINDOW_SECONDS = 60


def _root_causes(exc: BaseException) -> list[BaseException]:
    """Return the exception plus its causes, outermost first."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < _MAX_CAUSE_DEPTH:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _find(exc: BaseException, kind: type[BaseException]) -> BaseException | None:
    return next((e for e in _root_causes(exc) if isinstance(e, kind)), None)


def _describe_validation_error(exc: ValidationError) -> str:
    """Compress pydantic errors into one line per field the agent can act on.

    The raw pydantic text includes input echoes and documentation URLs that
    waste context and invite the model to quote them. We keep only the field
    path, the rule that failed and, for enums, the allowed values.
    """
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "call") or "args"
        message = err.get("msg", "invalid value")
        expected = (err.get("ctx") or {}).get("expected")
        if expected and str(expected) not in message:
            message = f"{message} (allowed: {expected})"
        parts.append(f"{loc}: {message}")
    return "; ".join(parts)


def _error_result(
    error: str, code: str, hint: str | None, *, retryable: bool
) -> ToolResult:
    return ToolResult(
        structured_content=ToolErrorResponse(
            error=error, error_code=code, hint=hint, retryable=retryable
        ).model_dump()
    )


class StructuredErrorsAndRateLimit(Middleware):
    """Return JSON errors and cap tool-call throughput per session.

    Error taxonomy (stable ``error_code`` values the agent can branch on):

    =====================  =========  ======================================
    error_code             retryable  meaning / what the agent should do
    =====================  =========  ======================================
    rate_limit_exceeded    yes        wait, then retry with a narrower scope
    invalid_arguments      no         fix the named field(s); same call fails
    refine_request         yes        valid input, but no usable data; change
                                      filters as the hint says
    upstream_unavailable   yes        OpenFEMA failed or throttled; retry
    internal_error         no         unexpected server fault; stop and
                                      report (details are logged, not shown)
    =====================  =========  ======================================
    """

    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def on_call_tool(self, context, call_next):
        # Two sliding-window buckets: a per-session limit (fairness between
        # agents) and a process-wide ceiling (protects OpenFEMA even when the
        # transport gives every request a fresh session id).
        limits = (
            (stable_session_key(context), settings.rate_limit_calls_per_minute,
             "this session"),
            (_GLOBAL_BUCKET, settings.rate_limit_global_calls_per_minute,
             "this server"),
        )
        now = time.time()
        async with self._lock:
            for key, limit, scope in limits:
                bucket = self._buckets[key]
                while bucket and now - bucket[0] >= _WINDOW_SECONDS:
                    bucket.popleft()
                if len(bucket) >= limit:
                    return _error_result(
                        f"Tool rate limit exceeded for {scope}. Pause or "
                        "narrow the review request before retrying.",
                        "rate_limit_exceeded",
                        "Wait a minute, then retry with a narrower scope.",
                        retryable=True,
                    )
            for key, _, _ in limits:
                self._buckets[key].append(now)
        try:
            return await call_next(context)
        except Exception as exc:  # noqa: BLE001 - this IS the error boundary
            return self._classify(exc)

    @staticmethod
    def _classify(exc: Exception) -> ToolResult:
        """Map any failure to one agent-recoverable error envelope.

        Order matters: FastMCP wraps signature-level schema failures in its
        own exception type with the pydantic error as the cause, so we search
        the whole cause chain rather than matching only the outer type.
        """
        validation = _find(exc, ValidationError)
        if validation is not None:
            return _error_result(
                "Tool arguments failed validation.",
                "invalid_arguments",
                _describe_validation_error(validation),  # type: ignore[arg-type]
                retryable=False,
            )
        upstream = _find(exc, UpstreamServiceError)
        if upstream is not None:
            return _error_result(
                str(upstream),
                "upstream_unavailable",
                "OpenFEMA did not return usable data. Retry shortly, or add "
                "disaster_number to reduce the request size.",
                retryable=True,
            )
        # Tools raise ValueError only with messages written for the agent
        # ("not found", "matches multiple projects", "not enough data"), so the
        # message itself is the safest, most specific hint.
        domain = _find(exc, ValueError)
        if domain is not None:
            message = str(domain)
            return _error_result(
                message,
                "refine_request",
                message,
                retryable=True,
            )
        # Anything else is a server bug. Never echo its text: it may contain
        # file paths or internals that help an attacker and confuse the model.
        # The full traceback goes to the server log for operators instead.
        logger.exception("Unhandled tool error", exc_info=exc)
        return _error_result(
            "Unexpected server error. No data was changed; this server is "
            "read-only.",
            "internal_error",
            "Do not retry the same call. Report the tool name and arguments.",
            retryable=False,
        )
