"""MCP resources that publish dataset provenance, guardrails, and methodology."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from fema_oversight.clients import DATASET_PROVENANCE
from fema_oversight.config import settings
from fema_oversight.methodology import (
    DAMAGE_CATEGORY_NAMES,
    INDICATOR_METHODOLOGY,
    TRIAGE_METHODOLOGY,
)
from fema_oversight.models import MAX_PAGE_SIZE

FIELD_DEFINITIONS = {
    "federalShareObligated": (
        "Federal PA funding available to the grantee. Typically 75% of total; "
        "some declarations authorized at 90%/100%."
    ),
    "totalObligated": "Federal share plus state and applicant administrative costs.",
    "projectAmount": (
        "Estimated total project cost from the damage survey, before admin costs."
    ),
    "damageCategoryCode": (
        "Single-letter PA category of work. A-B emergency work; C-G permanent work."
    ),
    "mitigationAmount": (
        "Section 406 hazard-mitigation portion. Can be negative due to "
        "adjustments; not an error."
    ),
}


def register(mcp: FastMCP) -> None:
    @mcp.resource("fema-pa://provenance")
    def provenance() -> str:
        """Dataset provenance and key field definitions for every live tool."""
        return json.dumps(
            {
                "provenance": DATASET_PROVENANCE,
                "field_definitions": FIELD_DEFINITIONS,
                "damage_categories": DAMAGE_CATEGORY_NAMES,
            },
            indent=2,
        )

    @mcp.resource("fema-pa://guardrails")
    def guardrails() -> str:
        """Security and governance controls enforced by this deployed server."""
        return json.dumps(
            {
                "read_only": True,
                "fixed_origin": "https://www.fema.gov/api/open/",
                "max_page_size": MAX_PAGE_SIZE,
                "rate_limit_calls_per_minute": settings.rate_limit_calls_per_minute,
                "rate_limit_global_calls_per_minute": (
                    settings.rate_limit_global_calls_per_minute
                ),
                "upstream_max_concurrency": settings.upstream_max_concurrency,
                "response_cache_ttl_seconds": settings.response_cache_ttl_seconds,
                "max_text_field_chars": settings.max_text_field_chars,
                "notes": [
                    "No write paths are implemented.",
                    (
                        "Caller-supplied URLs, queries, and OData path "
                        "overrides are rejected."
                    ),
                    "Tool errors are returned as structured JSON, not stack traces.",
                    (
                        "Free-text source fields are sanitized and truncated "
                        "before returning to an LLM."
                    ),
                ],
            },
            indent=2,
        )

    @mcp.resource("fema-pa://indicators")
    def indicators() -> str:
        """All fixed methodology cards plus the triage-combination rule."""
        return json.dumps(
            {
                "indicators": INDICATOR_METHODOLOGY,
                "triage_methodology": TRIAGE_METHODOLOGY,
            },
            indent=2,
        )
