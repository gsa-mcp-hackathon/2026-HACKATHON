"""Review tools: prioritize across indicators, explain a method, brief one worksheet."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastmcp import FastMCP

from fema_oversight import indicators
from fema_oversight.data_access import PAQuery, RecordSource, to_number
from fema_oversight.errors import ErrorCode, ReviewToolError
from fema_oversight.methodology import METHODOLOGY_CARDS, REVIEW_CAVEAT, REVIEW_STATUS, build_provenance
from fema_oversight.schemas.inputs import (
    EvidenceBriefRequest,
    ExplainIndicatorRequest,
    IndicatorType,
    ReviewQueueRequest,
)
from fema_oversight.schemas.outputs import (
    DataScope,
    EvidenceBrief,
    IndicatorCheck,
    MethodologyCard,
    QueueReason,
    ReviewQueueEntry,
    ReviewQueueResult,
    SourceRecord,
)
from fema_oversight.tools._registration import READ_ONLY_EXTERNAL, READ_ONLY_LOCAL, agent_errors

DEFAULT_SIGMA = 3.0
DEFAULT_BAND = (0.70, 0.95)
DEFAULT_MIN_TOTAL = 100_000.0
DEFAULT_MIN_REPEAT = 2
RECORD_CAP = 10_000

ALL_FIELDS = (
    "pwNumber",
    "applicantId",
    "stateAbbreviation",
    "county",
    "disasterNumber",
    "applicationTitle",
    "damageCategoryCode",
    "projectSize",
    "projectAmount",
    "totalObligated",
    "federalShareObligated",
    "declarationDate",
    "lastRefresh",
)

REVIEW_QUEUE_DESCRIPTION = """\
Build one prioritized review queue for a disaster by running all three screens (category cost
outliers in every damage category, repeated worksheet titles, and federal cost-share ratios)
with default thresholds and merging the results by worksheet.
USE WHEN the analyst asks where to start, what to review first, or for an overview of a
disaster ("what should I look at in Louisiana DR-4611?").
DO NOT USE when the question names one specific screen or custom thresholds; call that
screening tool instead.
Requires state_code and disaster_number. Worksheets flagged by more indicators rank higher,
then larger project amounts. Each entry lists every reason it was queued."""

EXPLAIN_DESCRIPTION = """\
Return the documented method for one review indicator: the question it answers, the exact
calculation, default thresholds, how to read results, limitations, and what it must not be
used for. Does not retrieve records.
USE WHEN someone asks how a result was produced, what an indicator means, or what it cannot
tell them. DO NOT USE to look up projects."""

EVIDENCE_BRIEF_DESCRIPTION = """\
Prepare the evidence package for one Project Worksheet an analyst has chosen to review: the
source records, a fresh re-computation of the indicator that flagged it, the methodology card,
suggested next review steps, and provenance.
USE WHEN the analyst selects a specific worksheet from a screening result or the review queue.
Pass disaster_number (and applicant_id when known) because PW numbers repeat across
applicants. DO NOT USE to screen many projects or to state a conclusion."""

NEXT_STEPS = {
    IndicatorType.CATEGORY_OUTLIER: [
        "Confirm the scope of work and cost estimate in the project record.",
        "Compare with similar projects for the same applicant or facility type.",
    ],
    IndicatorType.REPEATED_WORKSHEET: [
        "Open each worksheet in the group and compare site, facility, and scope.",
        "Confirm the worksheets cover distinct work before any further step.",
    ],
    IndicatorType.COST_SHARE_RATIO: [
        "Look up the cost share authorized for this declaration and period of work.",
        "Confirm the obligated federal share matches that authorization.",
    ],
}


def _identity(record: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (record.get("disasterNumber"), record.get("applicantId"), record.get("pwNumber"))


async def run_review_queue(params: ReviewQueueRequest, source: RecordSource) -> ReviewQueueResult:
    fetch = await source.fetch(
        PAQuery(
            fields=ALL_FIELDS,
            record_cap=RECORD_CAP,
            state_code=params.state_code,
            disaster_number=params.disaster_number,
        )
    )
    if not fetch.records:
        raise ReviewToolError(
            ErrorCode.NOT_FOUND,
            f"No public PA records for {params.state_code} disaster {params.disaster_number}.",
            "Check the state and disaster number pairing.",
        )
    reasons: dict[tuple, list[QueueReason]] = defaultdict(list)
    records_by_id = {_identity(r): r for r in fetch.records}
    totals = {indicator.value: 0 for indicator in IndicatorType}

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in fetch.records:
        by_category[str(record.get("damageCategoryCode"))].append(record)
    for category, rows in sorted(by_category.items()):
        baseline = indicators.category_baseline(rows)
        if baseline is None:
            continue
        for record, amount, sigma in indicators.category_outliers(rows, baseline, DEFAULT_SIGMA):
            totals[IndicatorType.CATEGORY_OUTLIER.value] += 1
            reasons[_identity(record)].append(
                QueueReason(
                    indicator=IndicatorType.CATEGORY_OUTLIER,
                    detail=f"${amount:,.2f} is {sigma:.2f} standard deviations above the category {category} mean.",
                )
            )
    for group in indicators.repeated_worksheet_groups(fetch.records, DEFAULT_MIN_REPEAT):
        totals[IndicatorType.REPEATED_WORKSHEET.value] += 1
        for record in group.records:
            reasons[_identity(record)].append(
                QueueReason(
                    indicator=IndicatorType.REPEATED_WORKSHEET,
                    detail=(
                        f"One of {len(group.records)} worksheets titled like "
                        f"'{group.title_pattern}' ({group.match_type})."
                    ),
                )
            )
    for record, _total, _federal, ratio in indicators.cost_share_outside_band(
        fetch.records, *DEFAULT_BAND, DEFAULT_MIN_TOTAL
    ):
        totals[IndicatorType.COST_SHARE_RATIO.value] += 1
        reasons[_identity(record)].append(
            QueueReason(
                indicator=IndicatorType.COST_SHARE_RATIO,
                detail=f"Federal share ratio {ratio:.4f} is outside {DEFAULT_BAND[0]}-{DEFAULT_BAND[1]}.",
            )
        )

    def priority(key: tuple) -> tuple:
        amount = to_number(records_by_id[key].get("projectAmount")) or 0.0
        return (-len({r.indicator for r in reasons[key]}), -amount, key[2] or 0)

    # OpenFEMA can return several rows for one worksheet; keep each reason once.
    for key, items in reasons.items():
        reasons[key] = list({(r.indicator, r.detail): r for r in items}.values())
    ranked = sorted((k for k in reasons if all(part is not None for part in k)), key=priority)
    queue = []
    for rank, key in enumerate(ranked[: params.limit], start=1):
        record = records_by_id[key]
        queue.append(
            ReviewQueueEntry(
                rank=rank,
                pw_number=key[2],
                applicant_id=key[1],
                disaster_number=key[0],
                application_title=record.get("applicationTitle"),
                damage_category_code=record.get("damageCategoryCode"),
                project_amount=to_number(record.get("projectAmount")),
                indicator_count=len({r.indicator for r in reasons[key]}),
                reasons=reasons[key],
            )
        )
    return ReviewQueueResult(
        queue=queue,
        total_worksheets_with_indicators=len(ranked),
        indicator_totals=totals,
        data_scope=DataScope(
            records_retrieved=len(fetch.records),
            record_cap=fetch.record_cap,
            possibly_truncated=fetch.possibly_truncated,
            filters={"state_code": params.state_code, "disaster_number": params.disaster_number},
        ),
        caveat=REVIEW_CAVEAT,
        provenance=build_provenance(
            fetch,
            f"Category outliers per damage category at sigma >= {DEFAULT_SIGMA}; repeated titles with "
            f">= {DEFAULT_MIN_REPEAT} worksheets; cost-share ratio outside {DEFAULT_BAND} for "
            f"totalObligated >= {DEFAULT_MIN_TOTAL:,.0f}. Ranked by distinct indicators, then projectAmount.",
            ["Default thresholds only; use a screening tool for custom thresholds."],
        ),
    )


def run_explain(params: ExplainIndicatorRequest) -> MethodologyCard:
    return METHODOLOGY_CARDS[params.indicator]


async def _check_indicator(indicator: IndicatorType, record: dict[str, Any], source: RecordSource) -> IndicatorCheck:
    """Re-run the triggering rule for one worksheet with default thresholds."""
    if indicator is IndicatorType.CATEGORY_OUTLIER:
        category = record.get("damageCategoryCode")
        peers = await source.fetch(
            PAQuery(
                fields=("pwNumber", "projectAmount", "damageCategoryCode"),
                record_cap=RECORD_CAP,
                state_code=record.get("stateAbbreviation"),
                disaster_number=record.get("disasterNumber"),
                damage_category_code=category,
            )
        )
        baseline = indicators.category_baseline(peers.records)
        amount = to_number(record.get("projectAmount"))
        if baseline is None or amount is None:
            return IndicatorCheck(
                indicator_met=False,
                measured_value="not computable",
                threshold=f"sigma >= {DEFAULT_SIGMA}",
                baseline=f"{len(peers.records)} category {category} records",
            )
        sigma = (amount - baseline.mean) / baseline.stddev
        return IndicatorCheck(
            indicator_met=sigma >= DEFAULT_SIGMA,
            measured_value=f"sigma {sigma:.2f} (${amount:,.2f})",
            threshold=f"sigma >= {DEFAULT_SIGMA}",
            baseline=f"{baseline.n} category {category} projects, mean ${baseline.mean:,.2f}, "
            f"population stddev ${baseline.stddev:,.2f}",
        )
    if indicator is IndicatorType.REPEATED_WORKSHEET:
        siblings = await source.fetch(
            PAQuery(
                fields=(
                    "pwNumber",
                    "applicantId",
                    "disasterNumber",
                    "applicationTitle",
                    "damageCategoryCode",
                    "federalShareObligated",
                ),
                record_cap=RECORD_CAP,
                disaster_number=record.get("disasterNumber"),
                applicant_id=record.get("applicantId"),
            )
        )
        pattern = indicators.title_pattern(record.get("applicationTitle"))
        group = [
            r
            for r in siblings.records
            if indicators.title_pattern(r.get("applicationTitle")) == pattern
            and r.get("damageCategoryCode") == record.get("damageCategoryCode")
        ]
        pws = sorted({r.get("pwNumber") for r in group if r.get("pwNumber") is not None})
        return IndicatorCheck(
            indicator_met=bool(pattern) and len(group) >= DEFAULT_MIN_REPEAT,
            measured_value=f"{len(group)} worksheets share title pattern '{pattern}': PW {pws}",
            threshold=f">= {DEFAULT_MIN_REPEAT} worksheets",
            baseline=f"{len(siblings.records)} worksheets for this applicant in this disaster",
        )
    total = to_number(record.get("totalObligated"))
    federal = to_number(record.get("federalShareObligated"))
    if not total or federal is None or total <= 0:
        return IndicatorCheck(
            indicator_met=False, measured_value="not computable", threshold=str(DEFAULT_BAND), baseline="this record"
        )
    ratio = federal / total
    return IndicatorCheck(
        indicator_met=total >= DEFAULT_MIN_TOTAL and not (DEFAULT_BAND[0] <= ratio <= DEFAULT_BAND[1]),
        measured_value=f"ratio {ratio:.4f} on total obligated ${total:,.2f}",
        threshold=f"outside {DEFAULT_BAND[0]}-{DEFAULT_BAND[1]} with total >= ${DEFAULT_MIN_TOTAL:,.0f}",
        baseline="this record",
    )


async def run_evidence_brief(params: EvidenceBriefRequest, source: RecordSource) -> EvidenceBrief:
    fetch = await source.fetch(
        PAQuery(
            fields=ALL_FIELDS,
            record_cap=50,
            disaster_number=params.disaster_number,
            pw_number=params.pw_number,
            applicant_id=params.applicant_id,
        )
    )
    if not fetch.records:
        raise ReviewToolError(
            ErrorCode.NOT_FOUND,
            f"No public worksheet PW {params.pw_number} in disaster {params.disaster_number}"
            + (f" for applicant {params.applicant_id}." if params.applicant_id else "."),
            "Copy pw_number, disaster_number, and applicant_id from a screening result.",
        )
    applicants = sorted({str(r.get("applicantId")) for r in fetch.records})
    if len(applicants) > 1:
        raise ReviewToolError(
            ErrorCode.AMBIGUOUS_IDENTITY,
            f"PW {params.pw_number} in disaster {params.disaster_number} belongs to {len(applicants)} applicants.",
            f"Call again with applicant_id set to one of: {', '.join(applicants[:10])}.",
        )
    primary = fetch.records[0]
    return EvidenceBrief(
        pw_number=params.pw_number,
        disaster_number=params.disaster_number,
        applicant_id=applicants[0],
        indicator=params.indicator,
        source_records=[
            SourceRecord(
                pw_number=r.get("pwNumber"),
                applicant_id=r.get("applicantId"),
                disaster_number=r.get("disasterNumber"),
                state=r.get("stateAbbreviation"),
                county=r.get("county"),
                application_title=r.get("applicationTitle"),
                damage_category_code=r.get("damageCategoryCode"),
                project_size=r.get("projectSize"),
                project_amount=to_number(r.get("projectAmount")),
                total_obligated=to_number(r.get("totalObligated")),
                federal_share_obligated=to_number(r.get("federalShareObligated")),
                declaration_date=r.get("declarationDate"),
            )
            for r in fetch.records
        ],
        indicator_check=await _check_indicator(params.indicator, primary, source),
        methodology=METHODOLOGY_CARDS[params.indicator],
        analyst_next_steps=NEXT_STEPS[params.indicator],
        review_status=REVIEW_STATUS,
        caveat=REVIEW_CAVEAT,
        provenance=build_provenance(
            fetch,
            f"Records where pwNumber = {params.pw_number} and disasterNumber = "
            f"{params.disaster_number}; indicator re-checked with default thresholds.",
        ),
    )


def register(mcp: FastMCP, source: RecordSource) -> None:
    @mcp.tool(
        name="build_review_queue",
        title="Build a prioritized review queue for a disaster",
        description=REVIEW_QUEUE_DESCRIPTION,
        annotations=READ_ONLY_EXTERNAL,
        tags={"review"},
    )
    @agent_errors
    async def build_review_queue(params: ReviewQueueRequest) -> ReviewQueueResult:
        return await run_review_queue(params, source)

    @mcp.tool(
        name="explain_review_indicator",
        title="Explain how a review indicator is calculated and its limits",
        description=EXPLAIN_DESCRIPTION,
        annotations=READ_ONLY_LOCAL,
        tags={"explanation"},
    )
    def explain_review_indicator(params: ExplainIndicatorRequest) -> MethodologyCard:
        return run_explain(params)

    @mcp.tool(
        name="prepare_evidence_brief",
        title="Prepare the evidence package for one Project Worksheet",
        description=EVIDENCE_BRIEF_DESCRIPTION,
        annotations=READ_ONLY_EXTERNAL,
        tags={"review"},
    )
    @agent_errors
    async def prepare_evidence_brief(params: EvidenceBriefRequest) -> EvidenceBrief:
        return await run_evidence_brief(params, source)
