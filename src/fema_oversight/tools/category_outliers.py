"""Tool: detect_category_outliers — high-level within-category cost screening."""

from __future__ import annotations

import statistics
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from fema_oversight.clients import PAFetchResult, openfema_client
from fema_oversight.methodology import DAMAGE_CATEGORY_NAMES, REVIEW_CAVEAT
from fema_oversight.models import (
    STATE_CODE_PATTERN,
    CategoryOutlierRequest,
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
    "projectAmount",
    "damageCategoryCode",
    "damageCategoryDescrip",
]
_RECORD_CAP = 10000


async def _get_records(flt: str) -> PAFetchResult:
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
        name="detect_category_outliers",
        annotations={
            "title": "Within-category cost outliers (review indicator)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def detect_category_outliers(
        damage_category_code: Annotated[
            str,
            Field(
                pattern=r"^[A-Ga-g]$",
                description=(
                    "FEMA category of work to baseline against. Use one letter A-G; "
                    "management-cost category Z is intentionally excluded."
                ),
                examples=["C", "E"],
            ),
        ],
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
        sigma_threshold: Annotated[
            float,
            Field(
                ge=1,
                le=10,
                description=(
                    "How many standard deviations above the category mean a project "
                    "must be before it is flagged."
                ),
                examples=[2.5, 3.0],
            ),
        ] = 3.0,
        pagination: Annotated[
            PaginationParams | None,
            Field(description="Pagination options for the returned outlier list."),
        ] = None,
        disaster_number: Annotated[
            int,
            Field(
                ge=0,
                description="Optional FEMA disaster declaration number.",
                examples=[0, 4734],
            ),
        ] = 0,
    ) -> dict[str, Any]:
        """Rank projects whose dollar amount is unusually high relative to other
        projects in the same FEMA work category.

        Use this when an analyst wants category-aware anomaly screening rather
        than absolute-dollar sorting. The tool builds a category-specific
        baseline, computes standard-deviation distance from that baseline, and
        returns the highest outliers first.

        Authoritative source: FEMA OpenFEMA Public Assistance Funded Projects
        Details (v2), a public read-only dataset refreshed daily.

        Interpret the output as a REVIEW INDICATOR only. A large bridge or major
        utility repair can be a legitimate high outlier.
        """
        request = CategoryOutlierRequest(
            damage_category_code=damage_category_code,
            state_code=state_code,
            sigma_threshold=sigma_threshold,
            pagination=pagination,
            disaster_number=disaster_number,
        )
        cat = request.damage_category_code
        clauses = [f"damageCategoryCode eq '{odata_quote(cat)}'"]
        if request.disaster_number:
            clauses.append(f"disasterNumber eq {request.disaster_number}")
        if request.state_code:
            clauses.append(f"stateAbbreviation eq '{odata_quote(request.state_code)}'")
        result = await _get_records(" and ".join(clauses))
        source_last_updated = await openfema_client.get_dataset_last_updated()

        amounts = [
            amount
            for amount in (to_float(r.get("projectAmount")) for r in result.records)
            if amount is not None
        ]
        if len(amounts) < 2:
            raise ValueError(
                "Not enough data to compute a category baseline. Widen the filter "
                "(remove the state, or pick another category)."
            )
        mean = statistics.fmean(amounts)
        sd = statistics.pstdev(amounts)
        if sd <= 0:
            raise ValueError(
                "Category has no cost variation to measure outliers against. Pick "
                "another category or widen the filter."
            )

        flagged = []
        for r in result.records:
            amt = to_float(r.get("projectAmount"))
            if amt is None:
                continue
            sigma = (amt - mean) / sd
            if sigma >= request.sigma_threshold:
                flagged.append(
                    {
                        "pw_number": r.get("pwNumber"),
                        "applicant_id": sanitize_text(r.get("applicantId")),
                        "state": sanitize_text(r.get("stateAbbreviation")),
                        "disaster_number": r.get("disasterNumber"),
                        "damage_category_code": cat,
                        "damage_category_name": DAMAGE_CATEGORY_NAMES.get(cat),
                        "damage_category_description": sanitize_text(
                            r.get("damageCategoryDescrip")
                        ),
                        "project_amount": round(amt, 2),
                        "category_mean": round(mean, 2),
                        "sigma_above_mean": round(sigma, 2),
                    }
                )
        flagged.sort(key=lambda x: x["sigma_above_mean"], reverse=True)

        pg = resolve_pagination(request.pagination)
        out = paginate(flagged, pg.limit, pg.offset)
        out["data_scope"] = build_data_scope(
            records_retrieved=len(result.records),
            record_cap=_RECORD_CAP,
            upstream_total_matches=result.total_matches,
            disaster_filter=request.disaster_number or None,
            baseline="retrieved projects in selected category and filters",
        )
        out["category_stats"] = {
            "damage_category_code": cat,
            "damage_category_name": DAMAGE_CATEGORY_NAMES.get(cat),
            "mean": round(mean, 2),
            "stddev": round(sd, 2),
            "n": len(amounts),
        }
        out["caveat"] = REVIEW_CAVEAT
        out["_provenance"] = provenance_block_from_result(
            f"sigma = (projectAmount - category_mean) / category_stddev within "
            f"category {cat}; flagged sigma >= {request.sigma_threshold}.",
            retrieval_timestamp=result.retrieved_at,
            source_last_updated=source_last_updated,
            limitations_suffix=(
                " Detection tools analyze at most 10,000 category records per call. "
                "Results and baselines describe the retrieved subset, not the full "
                "dataset. The baseline is not matched on declaration type, project "
                "scale or geography beyond the filters supplied."
            ),
        )
        return out
