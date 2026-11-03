"""Tool: generate_evidence_brief — package one flagged project for human review.

This is the "drill-down" step of the oversight workflow. A screening or triage
tool tells the analyst *which* worksheet to look at; this tool assembles the
authoritative source rows, the matching methodology card and the provenance an
analyst needs to write a case note, all in one call.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from fema_oversight.clients import PAFetchResult, openfema_client
from fema_oversight.methodology import INDICATOR_METHODOLOGY, REVIEW_CAVEAT
from fema_oversight.models import (
    ApplicantIdArg,
    DisasterNumberArg,
    EvidenceBriefRequest,
    IndicatorArg,
    PwNumberArg,
)
from fema_oversight.security import sanitize_text
from fema_oversight.utils import (
    fetch_pa_records,
    fetch_pa_records_with_meta,
    odata_quote,
    provenance_block_from_result,
    to_float,
)

_SELECT = [
    "pwNumber",
    "applicantId",
    "stateAbbreviation",
    "county",
    "disasterNumber",
    "applicationTitle",
    "damageCategoryCode",
    "damageCategoryDescrip",
    "projectAmount",
    "totalObligated",
    "federalShareObligated",
    "declarationDate",
]


# One worksheet identity rarely has more than a handful of versions; 50 rows is
# a generous ceiling that still keeps the brief small enough for an LLM context.
_BRIEF_ROW_CAP = 50


async def _get_records(flt: str) -> PAFetchResult:
    # Test seam: see triage_queue._get_records for why this check exists.
    if getattr(fetch_pa_records, "__module__", "") != "fema_oversight.utils":
        rows = await fetch_pa_records(
            odata_filter=flt, select=_SELECT, top=_BRIEF_ROW_CAP
        )
        return PAFetchResult(records=rows, total_matches=None, retrieved_at="")
    return await fetch_pa_records_with_meta(
        odata_filter=flt,
        select=_SELECT,
        top=_BRIEF_ROW_CAP,
        include_count=False,
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="generate_evidence_brief",
        annotations={
            "title": "Generate an evidence brief",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def generate_evidence_brief(
        pw_number: PwNumberArg,
        indicator: IndicatorArg,
        disaster_number: DisasterNumberArg = 0,
        applicant_id: ApplicantIdArg = "",
    ) -> dict[str, Any]:
        """Assemble the evidence packet a human reviewer needs for ONE Project
        Worksheet (PW) that a screening or triage tool already surfaced.

        USE WHEN the analyst says "tell me more about PW 169", "brief this
        project", or picks an item from build_oversight_triage_queue or a
        detector. Copy pw_number, disaster_number and applicant_id from that
        result; do not invent PW numbers.

        DO NOT USE to discover projects (use build_oversight_triage_queue) or
        to explain a method in general (use explain_risk_indicator).

        AUTHORITATIVE SOURCE: FEMA OpenFEMA Public Assistance Funded Projects
        Details v2 (public, read-only, refreshed daily).

        HOW TO READ THE OUTPUT: source_records are the verbatim public rows
        (dollar fields as reported); methodology and limitations come from the
        fixed card for the chosen indicator; _provenance cites the dataset and
        retrieval time. The brief does NOT re-run the screening threshold.

        RECOVERABLE ERRORS: "matches multiple projects" means retry with
        disaster_number AND applicant_id; "not found" means re-check the PW
        number against the screening result.
        """
        request = EvidenceBriefRequest(
            pw_number=pw_number,
            indicator=indicator,
            disaster_number=disaster_number,
            applicant_id=applicant_id,
        )
        card = INDICATOR_METHODOLOGY[request.indicator]
        clauses = [f"pwNumber eq {int(request.pw_number)}"]
        if request.disaster_number:
            clauses.append(f"disasterNumber eq {int(request.disaster_number)}")
        if request.applicant_id:
            clauses.append(f"applicantId eq '{odata_quote(request.applicant_id)}'")
        result = await _get_records(" and ".join(clauses))
        if not result.records:
            raise ValueError(
                f"No public worksheet {request.pw_number} found. Confirm the PW "
                "number from a detection tool result."
            )

        identities = {
            (r.get("disasterNumber"), r.get("applicantId")) for r in result.records
        }
        if len(identities) > 1:
            raise ValueError(
                "Worksheet number matches multiple projects. Supply disaster_number "
                "and applicant_id from the detection result."
            )
        source_last_updated = await openfema_client.get_dataset_last_updated()

        source_records = []
        for r in result.records:
            source_records.append(
                {
                    "pw_number": r.get("pwNumber"),
                    "applicant_id": sanitize_text(r.get("applicantId")),
                    "state": sanitize_text(r.get("stateAbbreviation")),
                    "county": sanitize_text(r.get("county")),
                    "disaster_number": r.get("disasterNumber"),
                    "application_title": sanitize_text(r.get("applicationTitle")),
                    "damage_category": sanitize_text(r.get("damageCategoryDescrip")),
                    "project_amount": to_float(r.get("projectAmount")),
                    "total_obligated": to_float(r.get("totalObligated")),
                    "federal_share_obligated": to_float(r.get("federalShareObligated")),
                    "declaration_date": sanitize_text(r.get("declarationDate")),
                }
            )

        return {
            "pw_number": request.pw_number,
            "indicator": request.indicator,
            "indicator_name": card["name"],
            "source_records": source_records,
            "rationale": (
                f"This Project Worksheet was submitted for {card['name']} review. "
                "This brief does not independently verify that the indicator "
                "threshold was met. Review the source records below against "
                "program context before drawing any conclusion."
            ),
            "methodology": card["methodology"],
            "limitations": card["limitations"],
            "review_status": "Not a finding. Analyst review required.",
            "caveat": REVIEW_CAVEAT,
            "_provenance": provenance_block_from_result(
                card["methodology"],
                retrieval_timestamp=result.retrieved_at,
                source_last_updated=source_last_updated,
                limitations_suffix=(
                    " Evidence briefs fetch at most 50 matching source rows for one "
                    "worksheet identity. The brief packages source records and the "
                    "selected methodology; it does not independently rerun the "
                    "screening threshold."
                ),
            ),
        }
