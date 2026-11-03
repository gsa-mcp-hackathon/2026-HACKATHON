"""Tool: explain_risk_indicator — publish the fixed methodology behind a signal.

Why a tool and not only a resource: MCP resources are pinned by the *client*,
whereas an LLM can decide to call a tool mid-conversation when a user asks
"why was this flagged?". The same cards are also published as the
``fema-pa://indicators`` resource so both paths read identical text.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from fema_oversight import __version__
from fema_oversight.clients import DATASET_PROVENANCE
from fema_oversight.methodology import INDICATOR_METHODOLOGY, REVIEW_CAVEAT
from fema_oversight.models import ExplainIndicatorRequest, IndicatorArg


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="explain_risk_indicator",
        annotations={
            "title": "Explain a risk indicator",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def explain_risk_indicator(indicator: IndicatorArg) -> dict[str, Any]:
        """Return the fixed, auditable methodology card for one review indicator.

        USE WHEN the user asks how a flag is calculated, what a threshold
        means, whether a flag implies fraud, or what the limitations are.
        Answer from this card instead of from general knowledge.

        DO NOT USE to fetch project data; this tool makes no network call.

        HOW TO READ THE OUTPUT: name, methodology, calculation, thresholds and
        limitations are static text versioned with the server. Quote
        limitations when presenting any flag to a human.
        """
        request = ExplainIndicatorRequest(indicator=indicator)
        card: dict[str, Any] = dict(INDICATOR_METHODOLOGY[request.indicator])
        card["indicator"] = request.indicator
        card["caveat"] = REVIEW_CAVEAT
        # Even a static answer carries provenance, so an auditor can tell which
        # server version and which dataset the methodology applies to.
        card["_provenance"] = {
            "source": f"fema_oversight.methodology (server v{__version__})",
            "applies_to_dataset": DATASET_PROVENANCE["source"],
            "dataset_url": DATASET_PROVENANCE["source_url"],
            "network_calls": 0,
            "review_status": REVIEW_CAVEAT,
        }
        return card
