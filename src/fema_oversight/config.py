"""Server configuration, loaded from environment variables or a ``.env`` file.

Every operational guardrail (rate limits, record caps, timeouts, cache TTLs)
lives here rather than as a literal inside a tool. That gives operators one
auditable place to tighten the server for a given deployment, and lets the
``fema-pa://guardrails`` resource publish the *actual* limits in force instead
of a hand-maintained copy that could drift.

Override any field with an environment variable of the same name in upper
case, e.g. ``RATE_LIMIT_CALLS_PER_MINUTE=30``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the FEMA oversight MCP server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Transport -----------------------------------------------------------
    # "stdio" for local desktop clients; "streamable-http" for hosted use.
    # Hosted platforms that inject DATABRICKS_APP_PORT/PORT override this.
    mcp_transport: str = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # --- Upstream (OpenFEMA) -------------------------------------------------
    upstream_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    # Bounded so one agent cannot fan out dozens of parallel calls against a
    # free public API and degrade it for other citizens.
    upstream_max_concurrency: int = Field(default=4, ge=1, le=16)
    # Identical OpenFEMA queries inside this window are served from memory.
    # The dataset refreshes daily, so a few minutes of reuse cannot produce a
    # stale answer in any meaningful sense, and it makes demos and evals fast.
    response_cache_ttl_seconds: float = Field(default=300.0, ge=0)
    response_cache_max_entries: int = Field(default=64, ge=0)
    # Look up OpenFEMA's published dataset refresh time for provenance.
    # Disabled in unit tests so they never touch the network.
    provenance_lookup_enabled: bool = True
    provenance_cache_ttl_seconds: float = Field(default=3600.0, ge=0)

    # --- Agent-facing guardrails ---------------------------------------------
    # Sliding-window limit on tool calls per MCP session (or per process when
    # the transport has no session id).
    rate_limit_calls_per_minute: int = Field(default=60, ge=1)
    # Process-wide ceiling across ALL sessions. This is the guaranteed
    # backstop: some transports (stateless HTTP, and FastMCP's in-memory
    # client) mint a new session id per request, which silently defeats a
    # per-session limit on its own. Found by eval/eval_runner.py.
    rate_limit_global_calls_per_minute: int = Field(default=600, ge=1)
    # NOTE: the per-page item ceiling (100) is deliberately NOT configurable.
    # It is published in every tool's JSON schema (models.MAX_PAGE_SIZE), and
    # a schema that disagrees with the server's behaviour misleads the agent.
    # Free-text fields copied from source records are truncated to this many
    # characters (see security.sanitize_text).
    max_text_field_chars: int = Field(default=200, ge=20)


settings = Settings()
