"""Input and output hardening helpers.

This server only reads public data, but tool outputs still flow into an LLM.
That creates a different security problem from classic API security: record text
can contain instructions, prompts, HTML, or path-like content that the model may
misread as commands. The helpers here preserve evidence value while stripping
prompt-injection leverage and bounding output size.
"""

from __future__ import annotations

import re
from typing import Any

from fema_oversight.config import settings

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE_RUN = re.compile(r"\s+")


def sanitize_text(value: Any, *, max_chars: int | None = None) -> str | None:
    """Return a bounded, display-safe version of a source text field.

    Rules:
    * ``None`` stays ``None``.
    * Non-string values are stringified so the caller can safely emit them.
    * Control characters are removed.
    * Newlines and repeated whitespace collapse to single spaces.
    * Extremely long fields are truncated with a marker.

    This is not about hiding evidence; it is about preventing source records from
    becoming executable instructions when echoed into an agent transcript.
    """
    if value is None:
        return None
    text = str(value)
    text = CONTROL_CHARS.sub("", text)
    text = WHITESPACE_RUN.sub(" ", text).strip()
    limit = max_chars or settings.max_text_field_chars
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 18)].rstrip() + " [truncated]"


def stable_session_key(context: Any) -> str:
    """Best-effort session identity for rate limiting.

    FastMCP transports do not all expose the same context fields. We prefer a
    real session id when present, otherwise fall back to a process-local bucket.
    That still protects hosted demos from runaway tool loops inside one worker.
    """
    fastmcp_context = getattr(context, "fastmcp_context", None)
    for attr in ("session_id", "connection_id", "request_id"):
        value = getattr(fastmcp_context, attr, None)
        if value:
            return f"session:{value}"
    return "session:process-local"
