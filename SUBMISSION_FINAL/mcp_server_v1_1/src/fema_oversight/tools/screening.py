"""Screening tools: one documented rule each, applied to a scoped set of records."""

from __future__ import annotations

from fastmcp import FastMCP

from fema_oversight import indicators
from fema_oversight.data_access import PAQuery, RecordSource
from fema_oversight.errors import ErrorCode, ReviewToolError
from fema_oversight.methodology import REVIEW_CAVEAT, build_provenance
from fema_oversight.schemas.inputs import CategoryOutlierRequest, CostShareRequest, RepeatedWorksheetRequest
from fema_oversight.schemas.outputs import (
    CategoryOutlierIndicator,
    CategoryOutlierResult,
    CategoryStats,
    CostShareIndicator,
    CostShareResult,
    DataScope,
    Page,
    RepeatedWorksheetGroup,
    RepeatedWorksheetResult,
)
from fema_oversight.tools._registration import READ_ONLY_EXTERNAL, agent_errors

SCREEN_RECORD_CAP = 10_000
COST_SHARE_RECORD_CAP = 5_000

CATEGORY_OUTLIER_DESCRIPTION = """\
Find Public Assistance projects whose estimated cost is far above other projects in the
same damage category, disaster, and state.
USE WHEN the question asks which projects are unusually expensive compared with similar
work (for example "utility repairs in Hurricane Ida", "roads and bridges in DR-4673").
DO NOT USE to judge eligibility or reasonableness of costs, or for repeated titles or
federal-share percentages (use the other screening tools).
Requires a damage category letter and at least one of state_code or disaster_number.
Returns projects ranked by standard deviations above the category mean, with the baseline,
record count, truncation flag, and provenance. Each result is a review indicator."""

REPEATED_WORKSHEET_DESCRIPTION = """\
Group Project Worksheets from the same applicant, disaster, and damage category whose titles
match after ignoring capitalization, punctuation, and standalone numbers.
USE WHEN the question asks whether the same project appears more than once, or whether an
applicant has many near-identical worksheets.
DO NOT USE to decide duplication of benefits, or for cost comparisons.
Requires state_code, disaster_number, or both. Groups are ordered closest match first:
same_wording (differ only by case or punctuation) before numbered_series (Site 1, Site 2),
which are often legitimate. Each group is a review indicator."""

COST_SHARE_DESCRIPTION = """\
Find obligations whose federal share (federalShareObligated / totalObligated) falls below
band_low or above band_high, for projects at or above min_total_obligated.
USE WHEN the question is about federal cost-share percentages in a state or disaster.
DO NOT USE to decide whether a share was authorized: declarations authorized at 90% or 100%
are legitimate and will appear; this tool does not check authorizations.
Requires state_code. Boundary values are not returned. Each result is a review indicator."""


def _page(total: int, offset: int, count: int) -> Page:
    next_offset = offset + count
    has_more = next_offset < total
    return Page(
        total=total, count=count, offset=offset, has_more=has_more, next_offset=next_offset if has_more else None
    )


def _scope(fetch, **filters) -> DataScope:
    return DataScope(
        records_retrieved=len(fetch.records),
        record_cap=fetch.record_cap,
        possibly_truncated=fetch.possibly_truncated,
        filters=filters,
    )


async def run_category_outliers(params: CategoryOutlierRequest, source: RecordSource) -> CategoryOutlierResult:
    category = params.damage_category_code.value
    query = PAQuery(
        fields=(
            "pwNumber",
            "applicantId",
            "stateAbbreviation",
            "county",
            "disasterNumber",
            "applicationTitle",
            "damageCategoryCode",
            "projectAmount",
            "lastRefresh",
        ),
        record_cap=SCREEN_RECORD_CAP,
        state_code=params.state_code,
        disaster_number=params.disaster_number,
        damage_category_code=category,
    )
    fetch = await source.fetch(query)
    baseline = indicators.category_baseline(fetch.records)
    if baseline is None:
        raise ReviewToolError(
            ErrorCode.INSUFFICIENT_DATA,
            f"Found {len(fetch.records)} category {category} records with usable amounts; "
            "at least 2 with different amounts are needed for a baseline.",
            "Remove a filter or choose another damage category.",
        )
    hits = indicators.category_outliers(fetch.records, baseline, params.sigma_threshold)
    window = hits[params.offset : params.offset + params.limit]
    return CategoryOutlierResult(
        indicators=[
            CategoryOutlierIndicator(
                pw_number=r.get("pwNumber"),
                applicant_id=r.get("applicantId"),
                disaster_number=r.get("disasterNumber"),
                state=r.get("stateAbbreviation"),
                county=r.get("county"),
                application_title=r.get("applicationTitle"),
                damage_category_code=r.get("damageCategoryCode"),
                project_amount=round(amount, 2),
                sigma_above_mean=round(sigma, 2),
            )
            for r, amount, sigma in window
        ],
        page=_page(len(hits), params.offset, len(window)),
        category_stats=CategoryStats(n=baseline.n, mean=round(baseline.mean, 2), stddev=round(baseline.stddev, 2)),
        data_scope=_scope(
            fetch, state_code=params.state_code, disaster_number=params.disaster_number, damage_category_code=category
        ),
        caveat=REVIEW_CAVEAT,
        provenance=build_provenance(
            fetch,
            f"sigma = (projectAmount - mean) / population_stddev within category {category}; "
            f"returned when sigma >= {params.sigma_threshold}.",
            ["Large legitimate infrastructure projects can be high outliers."],
        ),
    )


async def run_repeated_worksheets(params: RepeatedWorksheetRequest, source: RecordSource) -> RepeatedWorksheetResult:
    query = PAQuery(
        fields=(
            "pwNumber",
            "applicantId",
            "stateAbbreviation",
            "disasterNumber",
            "applicationTitle",
            "damageCategoryCode",
            "federalShareObligated",
            "lastRefresh",
        ),
        record_cap=SCREEN_RECORD_CAP,
        state_code=params.state_code,
        disaster_number=params.disaster_number,
    )
    fetch = await source.fetch(query)
    groups = indicators.repeated_worksheet_groups(fetch.records, params.min_repeat_count)
    window = groups[params.offset : params.offset + params.limit]
    return RepeatedWorksheetResult(
        groups=[
            RepeatedWorksheetGroup(
                applicant_id=g.applicant_id,
                disaster_number=g.disaster_number,
                state=g.records[0].get("stateAbbreviation"),
                damage_category_code=g.damage_category_code,
                title_pattern=g.title_pattern,
                match_type=g.match_type,
                worksheet_count=len(g.records),
                pw_numbers=sorted({r["pwNumber"] for r in g.records if r.get("pwNumber") is not None}),
                application_titles=g.titles[:10],
                distinct_title_count=len(g.titles),
                total_federal_share_obligated=g.federal_share_total,
            )
            for g in window
        ],
        page=_page(len(groups), params.offset, len(window)),
        data_scope=_scope(fetch, state_code=params.state_code, disaster_number=params.disaster_number),
        caveat=REVIEW_CAVEAT,
        provenance=build_provenance(
            fetch,
            "Group by disasterNumber, applicantId, title_pattern (lowercase, punctuation and "
            f"standalone numbers removed), damageCategoryCode; groups with >= {params.min_repeat_count} worksheets.",
            ["Numbered series (multiple sites or phases) are frequently legitimate."],
        ),
    )


async def run_cost_share(params: CostShareRequest, source: RecordSource) -> CostShareResult:
    query = PAQuery(
        fields=(
            "pwNumber",
            "applicantId",
            "stateAbbreviation",
            "disasterNumber",
            "totalObligated",
            "federalShareObligated",
            "lastRefresh",
        ),
        record_cap=COST_SHARE_RECORD_CAP,
        state_code=params.state_code,
        disaster_number=params.disaster_number,
        min_total_obligated=params.min_total_obligated,
    )
    fetch = await source.fetch(query)
    hits = indicators.cost_share_outside_band(
        fetch.records, params.band_low, params.band_high, params.min_total_obligated
    )
    window = hits[params.offset : params.offset + params.limit]
    return CostShareResult(
        indicators=[
            CostShareIndicator(
                pw_number=r.get("pwNumber"),
                applicant_id=r.get("applicantId"),
                disaster_number=r.get("disasterNumber"),
                state=r.get("stateAbbreviation"),
                total_obligated=round(total, 2),
                federal_share_obligated=round(federal, 2),
                federal_share_ratio=round(ratio, 4),
                position="below_band" if ratio < params.band_low else "above_band",
            )
            for r, total, federal, ratio in window
        ],
        page=_page(len(hits), params.offset, len(window)),
        policy_context=(
            "Threshold screen only. Declaration-specific authorized cost shares (for example 90% "
            "or 100% for a period of work) are not checked and will appear in results."
        ),
        data_scope=_scope(
            fetch,
            state_code=params.state_code,
            disaster_number=params.disaster_number,
            min_total_obligated=params.min_total_obligated,
        ),
        caveat=REVIEW_CAVEAT,
        provenance=build_provenance(
            fetch,
            "ratio = federalShareObligated / totalObligated; returned when ratio is outside "
            f"[{params.band_low}, {params.band_high}] and totalObligated >= {params.min_total_obligated}.",
            ["Declaration-specific cost-share authorizations are not verified."],
        ),
    )


def register(mcp: FastMCP, source: RecordSource) -> None:
    @mcp.tool(
        name="screen_category_cost_outliers",
        title="Screen for unusually expensive projects within a damage category",
        description=CATEGORY_OUTLIER_DESCRIPTION,
        annotations=READ_ONLY_EXTERNAL,
        tags={"screening"},
    )
    @agent_errors
    async def screen_category_cost_outliers(params: CategoryOutlierRequest) -> CategoryOutlierResult:
        return await run_category_outliers(params, source)

    @mcp.tool(
        name="find_repeated_worksheet_groups",
        title="Find groups of worksheets with matching titles",
        description=REPEATED_WORKSHEET_DESCRIPTION,
        annotations=READ_ONLY_EXTERNAL,
        tags={"screening"},
    )
    @agent_errors
    async def find_repeated_worksheet_groups(params: RepeatedWorksheetRequest) -> RepeatedWorksheetResult:
        return await run_repeated_worksheets(params, source)

    @mcp.tool(
        name="screen_cost_share_ratios",
        title="Screen federal cost-share ratios against an expected band",
        description=COST_SHARE_DESCRIPTION,
        annotations=READ_ONLY_EXTERNAL,
        tags={"screening"},
    )
    @agent_errors
    async def screen_cost_share_ratios(params: CostShareRequest) -> CostShareResult:
        return await run_cost_share(params, source)
