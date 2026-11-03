"""Tool: build_oversight_triage_queue — cross-indicator queue construction.

This is the server's clearest answer to the hackathon's "do not build thin
wrappers" requirement. Instead of making an LLM call three low-level detectors,
join the outputs itself, and invent a ranking rule, the tool performs the full
analyst action in one step and returns a review queue the model can use safely.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from fastmcp import FastMCP

from fema_oversight.clients import PAFetchResult, openfema_client
from fema_oversight.methodology import (
    DAMAGE_CATEGORY_NAMES,
    REVIEW_CAVEAT,
    TRIAGE_METHODOLOGY,
)
from fema_oversight.models import (
    BandHighArg,
    BandLowArg,
    DisasterNumberArg,
    MinRepeatCountArg,
    MinTotalObligatedArg,
    OversightTriageRequest,
    PaginationArg,
    SigmaThresholdArg,
    StateCodeArg,
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
    "county",
    "disasterNumber",
    "applicationTitle",
    "damageCategoryCode",
    "damageCategoryDescrip",
    "projectAmount",
    "totalObligated",
    "federalShareObligated",
]
_RECORD_CAP = 10000


async def _get_records(flt: str) -> PAFetchResult:
    # Test seam: unit tests and the offline eval harness monkeypatch
    # ``fetch_pa_records`` on this module with a plain-list fixture. When that
    # happens we skip the metadata-aware client so no network call is made.
    if getattr(fetch_pa_records, "__module__", "") != "fema_oversight.utils":
        rows = await fetch_pa_records(odata_filter=flt, select=_SELECT, top=_RECORD_CAP)
        return PAFetchResult(records=rows, total_matches=None, retrieved_at="")
    return await fetch_pa_records_with_meta(
        odata_filter=flt,
        select=_SELECT,
        top=_RECORD_CAP,
        include_count=True,
    )


def _key(record: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Project identity used to join indicator flags.

    pwNumber alone is NOT unique in OpenFEMA: the same PW number is reused
    across applicants and declarations, so joining on it would merge unrelated
    projects into one queue row.
    """
    return (
        record.get("disasterNumber"),
        record.get("applicantId"),
        record.get("pwNumber"),
    )


def _round_or_none(value: float | None) -> float | None:
    """Round dollars to cents but keep missing values visibly missing.

    Coercing None to 0.0 would tell the agent a project had zero dollars
    obligated when the source simply did not report the field.
    """
    return round(value, 2) if value is not None else None


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="build_oversight_triage_queue",
        annotations={
            "title": "Build oversight triage queue",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def build_oversight_triage_queue(
        state_code: StateCodeArg,
        min_total_obligated: MinTotalObligatedArg = 100000.0,
        band_low: BandLowArg = 0.70,
        band_high: BandHighArg = 0.95,
        sigma_threshold: SigmaThresholdArg = 3.0,
        min_repeat_count: MinRepeatCountArg = 2,
        pagination: PaginationArg = None,
        disaster_number: DisasterNumberArg = 0,
    ) -> dict[str, Any]:
        """Build ONE ranked human-review queue for a state by running all three
        FEMA Public Assistance review indicators over a single retrieval.

        USE WHEN the analyst asks "which projects should we review first?",
        "where should oversight focus in <state>?", or wants a prioritized
        worklist. Prefer this over calling the three detector tools one by one:
        it does the retrieval, cross-indicator join and ranking in one call.

        DO NOT USE for a single indicator family (call that detector), for one
        known worksheet (generate_evidence_brief), or for methodology questions
        (explain_risk_indicator).

        AUTHORITATIVE SOURCE: FEMA OpenFEMA Public Assistance Funded Projects
        Details v2 (public, read-only, refreshed daily).

        HOW TO READ THE OUTPUT:
        * items are sorted by indicator_count (how many indicators fired on the
          same project), then federal dollars obligated;
        * each item lists the indicators and the metric that triggered each;
        * data_scope.possibly_truncated=true means the state has more records
          than one call retrieves; add disaster_number to narrow the scope;
        * _provenance cites the dataset, its last refresh and retrieval time.

        NEXT STEP: pass an item's pw_number, disaster_number and applicant_id
        to generate_evidence_brief.

        Queue rank is a triage aid, not a conclusion. Convergence raises review
        priority only; it is never evidence of fraud, waste or abuse.
        """
        request = OversightTriageRequest(
            state_code=state_code,
            min_total_obligated=min_total_obligated,
            band_low=band_low,
            band_high=band_high,
            sigma_threshold=sigma_threshold,
            min_repeat_count=min_repeat_count,
            pagination=pagination,
            disaster_number=disaster_number,
        )
        clauses = [f"stateAbbreviation eq '{odata_quote(request.state_code)}'"]
        if request.disaster_number:
            clauses.append(f"disasterNumber eq {request.disaster_number}")
        result = await _get_records(" and ".join(clauses))
        source_last_updated = await openfema_client.get_dataset_last_updated()

        # Repeated worksheet grouping first because one group can implicate many PWs.
        repeated_group_map: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        repeated_groups: dict[
            tuple[Any, Any, Any, Any], list[dict[str, Any]]
        ] = defaultdict(list)
        for row in result.records:
            group_key = (
                row.get("disasterNumber"),
                row.get("applicantId"),
                row.get("applicationTitle"),
                row.get("damageCategoryCode"),
            )
            if all(v is not None for v in group_key):
                repeated_groups[group_key].append(row)
        for (disaster, applicant_id, title, category), rows in repeated_groups.items():
            if len(rows) < request.min_repeat_count:
                continue
            dollars = sum(to_float(r.get("federalShareObligated")) or 0.0 for r in rows)
            group_summary = {
                "application_title": sanitize_text(title),
                "worksheet_count": len(rows),
                "total_group_federal_share": round(dollars, 2),
                "damage_category_code": sanitize_text(category),
            }
            for row in rows:
                repeated_group_map[_key(row)] = group_summary

        # Category-specific baselines over the same retrieved subset.
        category_amounts: dict[str, list[float]] = defaultdict(list)
        for row in result.records:
            category = row.get("damageCategoryCode")
            amount = to_float(row.get("projectAmount"))
            if category in DAMAGE_CATEGORY_NAMES and amount is not None:
                category_amounts[category].append(amount)
        category_stats: dict[str, tuple[float, float, int]] = {}
        for category, amounts in category_amounts.items():
            if len(amounts) >= 2:
                mean = statistics.fmean(amounts)
                stddev = statistics.pstdev(amounts)
                category_stats[category] = (mean, stddev, len(amounts))

        queue = []
        for row in result.records:
            total = to_float(row.get("totalObligated"))
            fed = to_float(row.get("federalShareObligated"))
            project_amount = to_float(row.get("projectAmount"))
            category = row.get("damageCategoryCode")
            key = _key(row)
            indicators = []
            metrics: dict[str, Any] = {}

            if (
                total is not None
                and total > 0
                and total >= request.min_total_obligated
                and fed is not None
            ):
                ratio = fed / total
                if ratio < request.band_low or ratio > request.band_high:
                    indicators.append("cost_share_anomaly")
                    metrics["federal_share_ratio"] = round(ratio, 4)

            repeated = repeated_group_map.get(key)
            if repeated:
                indicators.append("repeated_worksheet")
                metrics["repeated_group"] = repeated

            stats = category_stats.get(category)
            if stats and project_amount is not None:
                mean, stddev, baseline_n = stats
                if stddev > 0:
                    sigma = (project_amount - mean) / stddev
                    if sigma >= request.sigma_threshold:
                        indicators.append("category_outlier")
                        metrics["sigma_above_mean"] = round(sigma, 2)
                        metrics["category_mean"] = round(mean, 2)
                        metrics["category_baseline_n"] = baseline_n

            if not indicators:
                continue
            queue.append(
                {
                    "pw_number": row.get("pwNumber"),
                    "applicant_id": sanitize_text(row.get("applicantId")),
                    "state": sanitize_text(row.get("stateAbbreviation")),
                    "county": sanitize_text(row.get("county")),
                    "disaster_number": row.get("disasterNumber"),
                    "application_title": sanitize_text(
                        row.get("applicationTitle")
                    ),
                    "damage_category_code": sanitize_text(category),
                    "damage_category_name": DAMAGE_CATEGORY_NAMES.get(category),
                    "project_amount": _round_or_none(project_amount),
                    "total_obligated": _round_or_none(total),
                    "federal_share_obligated": _round_or_none(fed),
                    "indicator_count": len(indicators),
                    "indicators": indicators,
                    "priority_reason": (
                        "Multiple indicator convergence"
                        if len(indicators) > 1
                        else f"Single indicator: {indicators[0]}"
                    ),
                    "metrics": metrics,
                }
            )

        queue.sort(
            key=lambda x: (
                x["indicator_count"],
                x.get("federal_share_obligated") or 0,
                x.get("project_amount") or 0,
            ),
            reverse=True,
        )

        pg = resolve_pagination(request.pagination)
        out = paginate(queue, pg.limit, pg.offset)
        out["triage_methodology"] = TRIAGE_METHODOLOGY
        out["indicator_parameters"] = {
            "band_low": request.band_low,
            "band_high": request.band_high,
            "sigma_threshold": request.sigma_threshold,
            "min_repeat_count": request.min_repeat_count,
            "min_total_obligated": request.min_total_obligated,
        }
        out["data_scope"] = build_data_scope(
            records_retrieved=len(result.records),
            record_cap=_RECORD_CAP,
            upstream_total_matches=result.total_matches,
            disaster_filter=request.disaster_number or None,
            baseline=(
                "single jurisdictional retrieval shared by all three indicators"
            ),
        )
        out["caveat"] = REVIEW_CAVEAT
        out["_provenance"] = provenance_block_from_result(
            TRIAGE_METHODOLOGY,
            retrieval_timestamp=result.retrieved_at,
            source_last_updated=source_last_updated,
            limitations_suffix=(
                " The triage queue analyzes at most 10,000 jurisdiction records in "
                "one call. Category baselines are computed only from that retrieved "
                "subset. Convergence across indicators raises review priority only; "
                "it does not establish error, waste, fraud or abuse."
            ),
        )
        return out
