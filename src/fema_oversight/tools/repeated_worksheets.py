"""Tool: find_repeated_worksheets — high-level duplicate/fragmentation screening."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from fema_oversight.clients import PAFetchResult, openfema_client
from fema_oversight.methodology import REVIEW_CAVEAT
from fema_oversight.models import (
    STATE_CODE_PATTERN,
    PaginationParams,
    RepeatedWorksheetsRequest,
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
    "applicationTitle",
    "damageCategoryCode",
    "damageCategoryDescrip",
    "federalShareObligated",
]
_RECORD_CAP = 10000


async def _get_records(flt: str | None) -> PAFetchResult:
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
        name="find_repeated_worksheets",
        annotations={
            "title": "Repeated worksheets (review indicator)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def find_repeated_worksheets(
        state_code: Annotated[
            str,
            Field(
                description=(
                    "Optional two-letter USPS state or territory code. Leave empty "
                    "to search all jurisdictions."
                ),
                pattern=f"^$|{STATE_CODE_PATTERN}",
                examples=["", "FL"],
            ),
        ] = "",
        disaster_number: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "Optional FEMA disaster declaration number. Use 0 to search all "
                    "declarations."
                ),
                examples=[0, 4673],
            ),
        ] = 0,
        min_repeat_count: Annotated[
            int,
            Field(
                ge=2,
                description=(
                    "Minimum number of matching worksheets required before a group "
                    "is returned for human review."
                ),
                examples=[2, 3],
            ),
        ] = 2,
        pagination: Annotated[
            PaginationParams | None,
            Field(description="Pagination options for the returned review groups."),
        ] = None,
    ) -> dict[str, Any]:
        """Find applicants whose public Project Worksheets repeat the same title and
        damage category often enough to merit fragmentation or duplication review.

        Use this when an analyst asks for repeated worksheet patterns inside a
        state or declaration. The tool groups records into reviewable cases,
        counts the repeated worksheets, sums federal dollars across the group,
        and returns the strongest groups first.

        Authoritative source: FEMA OpenFEMA Public Assistance Funded Projects
        Details (v2), a public read-only dataset refreshed daily.

        A repeated title pattern is a REVIEW INDICATOR only. Many are legitimate
        phased or multi-site projects.
        """
        request = RepeatedWorksheetsRequest(
            state_code=state_code,
            disaster_number=disaster_number,
            min_repeat_count=min_repeat_count,
            pagination=pagination,
        )
        clauses = []
        if request.state_code:
            clauses.append(f"stateAbbreviation eq '{odata_quote(request.state_code)}'")
        if request.disaster_number:
            clauses.append(f"disasterNumber eq {int(request.disaster_number)}")
        flt = " and ".join(clauses) if clauses else None
        result = await _get_records(flt)
        source_last_updated = await openfema_client.get_dataset_last_updated()

        groups: dict[
            tuple[Any, Any, Any, Any], list[dict[str, Any]]
        ] = defaultdict(list)
        for r in result.records:
            key = (
                r.get("disasterNumber"),
                r.get("applicantId"),
                r.get("applicationTitle"),
                r.get("damageCategoryCode"),
            )
            if all(k is not None for k in key):
                groups[key].append(r)

        flagged = []
        for (disaster, applicant_id, title, _cat), rows in groups.items():
            if len(rows) >= request.min_repeat_count:
                fed = sum(to_float(x.get("federalShareObligated")) or 0.0 for x in rows)
                flagged.append(
                    {
                        "applicant_id": sanitize_text(applicant_id),
                        "disaster_number": disaster,
                        "pw_numbers": sorted(
                            {
                                r.get("pwNumber")
                                for r in rows
                                if r.get("pwNumber") is not None
                            }
                        ),
                        "state": sanitize_text(rows[0].get("stateAbbreviation")),
                        "application_title": sanitize_text(title),
                        "damage_category_description": sanitize_text(
                            rows[0].get("damageCategoryDescrip")
                        ),
                        "worksheet_count": len(rows),
                        "total_federal_share_obligated": round(fed, 2),
                    }
                )
        flagged.sort(
            key=lambda x: (x["worksheet_count"], x["total_federal_share_obligated"]),
            reverse=True,
        )

        pg = resolve_pagination(request.pagination)
        out = paginate(flagged, pg.limit, pg.offset)
        out["data_scope"] = build_data_scope(
            records_retrieved=len(result.records),
            record_cap=_RECORD_CAP,
            upstream_total_matches=result.total_matches,
            disaster_filter=request.disaster_number or None,
        )
        out["caveat"] = REVIEW_CAVEAT
        out["_provenance"] = provenance_block_from_result(
            "Grouped by disasterNumber, applicantId, applicationTitle, "
            "damageCategoryCode; "
            f"flagged groups with count >= {request.min_repeat_count}.",
            retrieval_timestamp=result.retrieved_at,
            source_last_updated=source_last_updated,
            limitations_suffix=(
                " Detection tools analyze at most 10,000 repeated-worksheet "
                "records per call. Results describe the retrieved subset, not the "
                "full dataset. Repeated titles are often legitimate phased or "
                "multi-site work."
            ),
        )
        return out
