"""FastMCP server assembly and entry point.

``build_server`` is the only place components are wired together. Passing a
``RecordSource`` lets tests and the evaluation harness run the exact production
tools against archived snapshots.
"""

from __future__ import annotations

import json
import os

from fastmcp import FastMCP

from fema_oversight import __version__
from fema_oversight.data_access import CachingRecordSource, OpenFEMASource, RecordSource
from fema_oversight.methodology import DATASET, DATASET_LIMITATIONS, FIELD_DEFINITIONS, METHODOLOGY_CARDS
from fema_oversight.observability import configure_structured_logging, telemetry
from fema_oversight.tools import review, screening

SERVER_INSTRUCTIONS = """Read-only evidence tools over OpenFEMA Public Assistance Funded Projects Details (v2).
Start with build_review_queue for "where do I start" questions about a disaster; use a
screening tool when the question names one rule or custom thresholds; use
prepare_evidence_brief for one worksheet; use explain_review_indicator for "how was this
calculated". Every result is a review indicator, not a determination: report counts and
identifiers exactly as returned, include the provenance, and leave decisions to the analyst."""


def build_server(source: RecordSource | None = None) -> FastMCP:
    """Create the MCP server. Defaults to the live OpenFEMA source."""
    configure_structured_logging()
    records = source or CachingRecordSource(OpenFEMASource())
    mcp = FastMCP(
        name="FEMA Evidence & Oversight Graph",
        version=__version__,
        instructions=SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )
    screening.register(mcp, records)
    review.register(mcp, records)

    @mcp.resource(
        "fema-pa://provenance",
        name="dataset_provenance",
        description="Dataset source, publisher, refresh cadence, limitations, and field definitions.",
        mime_type="application/json",
    )
    def dataset_provenance() -> str:
        return json.dumps({**DATASET, "limitations": DATASET_LIMITATIONS, "fields": FIELD_DEFINITIONS}, indent=2)

    @mcp.resource(
        "fema-pa://methodology",
        name="indicator_methodology",
        description="Methodology cards for every review indicator.",
        mime_type="application/json",
    )
    def indicator_methodology() -> str:
        return json.dumps([card.model_dump(mode="json") for card in METHODOLOGY_CARDS.values()], indent=2)

    @mcp.resource(
        "fema-pa://metrics",
        name="operational_metrics",
        description=(
            "Process-local aggregate tool counts, failures, and latency. "
            "Contains no tool arguments or FEMA records and resets on restart."
        ),
        mime_type="application/json",
    )
    def operational_metrics() -> str:
        return json.dumps(telemetry.snapshot(), indent=2)

    @mcp.prompt(
        name="disaster_review",
        description="Standard evidence-first review of one disaster: queue, explain, brief, hand off.",
    )
    def disaster_review(state_code: str, disaster_number: int) -> str:
        return (
            f"Review {state_code} disaster {disaster_number}. 1) Call build_review_queue. "
            "2) For the top entry, call prepare_evidence_brief with its pw_number, "
            "disaster_number, applicant_id, and first indicator. 3) If asked how a result was "
            "computed, call explain_review_indicator. Report numbers exactly as returned, cite "
            "provenance.retrieved_at and the rule, and end with: Analyst review required."
        )

    return mcp


def main() -> None:
    """Run over stdio locally, or HTTP when a platform provides a port."""
    server = build_server()
    port = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")
    if port:
        server.run(transport="http", host="0.0.0.0", port=int(port))
    else:
        server.run()


if __name__ == "__main__":
    main()
