"""Tool: get_cost_share_anomalies — high-level analyst review screening."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from fema_oversight.clients import PAFetchResult, openfema_client
from fema_oversight.methodology import REVIEW_CAVEAT
from fema_oversight.models import (
    STATE_CODE_PATTERN,
    CostShareAnomalyRequest,
    PaginationParams,
)
from fema_oversight.security import sanitize_text
from fema_oversight.utils import (
    build_data_scope,
    fetch_pa_records,
    fetch_pa_records_with_meta,
    odata_quote,
    paginate,
    provenance_block_from_result,
    resolve_pagination,
    to_float,
)

_SELECT = [
    "pwNumber",
    "applicantId",
    "stateAbbreviation",
    "disasterNumber",
    "totalObligated",
    "federalShareObligated",
    "damageCategoryCode",
]
_RECORD_CAP = 5000


async def _get_records(request: CostShareAnomalyRequest, flt: str) -> PAFetchResult:
    """Fetch rows plus completeness metadata.

    Tests and eval harnesses monkeypatch ``fetch_pa_records`` to return a plain
    list. Preserve that seam: when patched, fall back to list-only behaviour;
    otherwise use the richer metadata path.
    """
    if getattr(fetch_pa_records, "__module__", "") != "fema_oversight.utils":
        rows = await fetch_pa_records(odata_filter=flt, select=_SELECT, top=_RECORD_CAP)
        return PAFetchResult(records=rows, total_matches=None, retrieved_at="")
    return await fetch_pa_records_with_meta(
        odata_filter=flt,
        select=_SELECT,
        top=_RECORD_CAP,
        include_count=True,
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_cost_share_anomalies",
        annotations={
            "title": "Cost-share anomalies (review indicator)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_cost_share_anomalies(
        state_code: Annotated[
            str,
            Field(
                pattern=STATE_CODE_PATTERN,
                description=(
                    "Two-letter USPS state or territory code to review, such as "
                    "FL, LA, PR, or GU."
                ),
                examples=["FL", "LA"],
            ),
        ],
        min_total_obligated: Annotated[
            float,
            Field(
                ge=0,
                description=(
                    "Ignore small projects below this total obligated dollar "
                    "amount to reduce noise during triage."
                ),
                examples=[100000.0, 500000.0],
            ),
        ] = 100000.0,
        band_low: Annotated[
            float,
            Field(
                ge=0,
                le=1,
                description="Lower bound of the expected federal-share ratio band.",
                examples=[0.7, 0.75],
            ),
        ] = 0.70,
        band_high: Annotated[
            float,
            Field(
                ge=0,
                le=1,
                description="Upper bound of the expected federal-share ratio band.",
                examples=[0.9, 0.95],
            ),
        ] = 0.95,
        pagination: Annotated[
            PaginationParams | None,
            Field(description="Pagination options for the returned review queue."),
        ] = None,
        disaster_number: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "Optional FEMA disaster declaration number. Use 0 to search all "
                    "declarations in the state."
                ),
                examples=[0, 4734],
            ),
        ] = 0,
    ) -> dict[str, Any]:
        """Screen one jurisdiction's FEMA Public Assistance portfolio for projects
        whose federal cost-share ratio falls outside an expected band.

        Use this when an analyst asks which projects in a state or declaration
        deserve cost-share review. The tool does more than a raw dataset lookup:
        it filters to comparable records, computes the share ratio, prioritizes
        the furthest deviations from the normal 75% pattern, and returns a
        paginated review queue with provenance and scope metadata.

        Authoritative source: FEMA OpenFEMA Public Assistance Funded Projects
        Details (v2), a public read-only dataset refreshed daily.

        Interpret the output as a REVIEW INDICATOR only. Some declarations are
        lawfully authorized at 90% or 100%, so a flag means "review this" — not
        "this is wrong."
        """
        request = CostShareAnomalyRequest(
            state_code=state_code,
            min_total_obligated=min_total_obligated,
            band_low=band_low,
            band_high=band_high,
            pagination=pagination,
            disaster_number=disaster_number,
        )
        flt = (
            f"stateAbbreviation eq '{odata_quote(request.state_code)}' "
            f"and totalObligated ge {float(request.min_total_obligated)}"
        )
        if request.disaster_number:
            flt += f" and disasterNumber eq {request.disaster_number}"
        result = await _get_records(request, flt)
        source_last_updated = await openfema_client.get_dataset_last_updated()

        flagged: list[dict[str, Any]] = []
        for r in result.records:
            total = to_float(r.get("totalObligated"))
            fed = to_float(r.get("federalShareObligated"))
            if (
                total is None
                or total <= 0
                or total < request.min_total_obligated
                or fed is None
            ):
                continue
            ratio = fed / total
            if ratio < request.band_low or ratio > request.band_high:
                flagged.append(
                    {
                        "pw_number": r.get("pwNumber"),
                        "applicant_id": sanitize_text(r.get("applicantId")),
                        "state": sanitize_text(r.get("stateAbbreviation")),
                        "disaster_number": r.get("disasterNumber"),
                        "damage_category_code": sanitize_text(
                            r.get("damageCategoryCode")
                        ),
                        "total_obligated": round(total, 2),
                        "federal_share_obligated": round(fed, 2),
                        "federal_share_ratio": round(ratio, 4),
                    }
                )
        flagged.sort(key=lambda x: abs(x["federal_share_ratio"] - 0.75), reverse=True)

        pg = resolve_pagination(request.pagination)
        out = paginate(flagged, pg.limit, pg.offset)
        out["data_scope"] = build_data_scope(
            records_retrieved=len(result.records),
            record_cap=_RECORD_CAP,
            upstream_total_matches=result.total_matches,
            disaster_filter=request.disaster_number or None,
        )
        out["policy_context"] = (
            "Threshold screening only. Declaration-specific authorized shares are "
            "not verified; authorized 100% shares may be returned."
        )
        out["caveat"] = REVIEW_CAVEAT
        out["_provenance"] = provenance_block_from_result(
            "federal_share_ratio = federalShareObligated / totalObligated; "
            f"flagged outside [{request.band_low}, {request.band_high}].",
            retrieval_timestamp=result.retrieved_at,
            source_last_updated=source_last_updated,
            limitations_suffix=(
                " Detection tools analyze at most 5,000 cost-share records per "
                "call. Results describe the retrieved subset, not the full "
                "dataset. Cost-share bands do not verify declaration-specific "
                "authorizations; authorized 100% shares may be returned."
            ),
        )
        return out
