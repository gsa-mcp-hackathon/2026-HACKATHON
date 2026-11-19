"""Documented methods, limitations, and provenance text.

This is the single place where the meaning of each indicator is written down.
Tools, the explanation tool, the evidence brief, and the MCP resource all read
from here, so an explanation can never drift from the rule that was executed.
"""

from __future__ import annotations

from fema_oversight.data_access import FetchResult
from fema_oversight.schemas.inputs import IndicatorType
from fema_oversight.schemas.outputs import MethodologyCard, Provenance

REVIEW_CAVEAT = (
    "Review indicator on public OpenFEMA data. It prioritizes records for analyst "
    "review and is not a determination. A person decides what, if anything, follows."
)

REVIEW_STATUS = "Analyst review required."

DATASET = {
    "source": "FEMA OpenFEMA Public Assistance Funded Projects Details (v2)",
    "source_url": "https://www.fema.gov/openfema-data-page/public-assistance-funded-projects-details-v2",
    "publisher": "FEMA / U.S. Department of Homeland Security",
    "update_frequency": "daily",
}

DATASET_LIMITATIONS = [
    "Figures come from FEMA Grants Manager, not FEMA's official financial system; not for official reporting.",
    "Statistics describe the retrieved records only; check data_scope.possibly_truncated.",
]

FIELD_DEFINITIONS = {
    "projectAmount": "Estimated total cost of the project worksheet.",
    "totalObligated": "Federal share plus non-federal share obligated to date.",
    "federalShareObligated": "Federal share obligated to date.",
    "damageCategoryCode": "PA category of work, A through G.",
    "pwNumber": "Project Worksheet number; unique only within a disaster and applicant.",
    "applicantId": "FEMA applicant identifier.",
}

METHODOLOGY_CARDS: dict[IndicatorType, MethodologyCard] = {
    IndicatorType.CATEGORY_OUTLIER: MethodologyCard(
        indicator=IndicatorType.CATEGORY_OUTLIER,
        name="Within-category cost outlier",
        question_answered="Which projects cost far more than other projects of the same kind of work?",
        calculation=(
            "sigma = (projectAmount - mean) / population_stddev, where mean and stddev are "
            "computed over retrieved projects in the same damage category and filters."
        ),
        default_thresholds="Returned when sigma >= 3.0 (configurable 1-10).",
        how_to_read=(
            "Higher sigma means further above comparable projects. Large legitimate "
            "infrastructure projects are expected to appear."
        ),
        limitations="Baseline is the retrieved subset only; project scale and geography are not matched.",
        not_for="Judging eligibility, reasonableness, or allowability of costs.",
    ),
    IndicatorType.REPEATED_WORKSHEET: MethodologyCard(
        indicator=IndicatorType.REPEATED_WORKSHEET,
        name="Repeated worksheet titles",
        question_answered="Does the same applicant have several worksheets that look like the same project?",
        calculation=(
            "title_pattern = applicationTitle lowercased, non-alphanumeric characters removed, "
            "standalone numbers removed; group by disaster, applicant, title_pattern, damage "
            "category; return groups with at least min_repeat_count worksheets."
        ),
        default_thresholds="min_repeat_count = 2.",
        how_to_read=(
            "same_wording groups (titles differ only by case or punctuation) are the closest "
            "matches. numbered_series groups (Site 1, Site 2) are common and usually legitimate."
        ),
        limitations="Titles with different wording or spelling are not matched.",
        not_for="Testing duplication of benefits, which is a separate determination.",
    ),
    IndicatorType.COST_SHARE_RATIO: MethodologyCard(
        indicator=IndicatorType.COST_SHARE_RATIO,
        name="Federal cost-share ratio outside band",
        question_answered="Which obligations have a federal share percentage outside the expected range?",
        calculation=(
            "ratio = federalShareObligated / totalObligated for projects with totalObligated >= "
            "min_total_obligated; returned when ratio < band_low or ratio > band_high."
        ),
        default_thresholds="Band 0.70-0.95; min_total_obligated $100,000.",
        how_to_read=(
            "PA is normally 75% federal. Declarations authorized at 90% or 100% will appear "
            "and are expected; compare each result with the declaration's authorized share."
        ),
        limitations="Declaration-specific cost-share authorizations are not checked.",
        not_for="Deciding whether a cost share was authorized.",
    ),
}


def build_provenance(fetch: FetchResult, rule: str, extra_limits: list[str] | None = None) -> Provenance:
    """Provenance block attached to every response that contains records."""
    return Provenance(
        **DATASET,
        retrieved_at=fetch.retrieved_at,
        source_last_refresh=fetch.source_last_refresh,
        rule=rule,
        limitations=DATASET_LIMITATIONS + (extra_limits or []),
        review_status=REVIEW_STATUS,
    )
