"""Typed result models returned by every tool.

FastMCP publishes these as each tool's ``outputSchema`` and returns them as
``structuredContent``, so an agent receives validated JSON whose every field is
documented, not free text it has to parse.

Shared blocks:

* ``Provenance``  where the data came from, when, by which rule, with which limits
* ``DataScope``   how many records were screened and whether the cap was hit
* ``Page``        pagination for list results
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from fema_oversight.schemas.inputs import IndicatorType


class Provenance(BaseModel):
    source: str = Field(description="Dataset name and version.")
    source_url: str
    publisher: str
    retrieved_at: str = Field(description="UTC ISO-8601 time the records were retrieved.")
    source_last_refresh: str | None = Field(
        None, description="Latest lastRefresh value among retrieved records, if present."
    )
    update_frequency: str
    rule: str = Field(description="The exact rule and parameters executed.")
    limitations: list[str]
    review_status: str


class DataScope(BaseModel):
    records_retrieved: int
    record_cap: int
    possibly_truncated: bool = Field(description="True when the record cap was reached; results may be incomplete.")
    filters: dict[str, str | int | float | None]


class Page(BaseModel):
    total: int = Field(description="Total results before pagination.")
    count: int
    offset: int
    has_more: bool
    next_offset: int | None


class CategoryStats(BaseModel):
    n: int = Field(description="Projects with a numeric projectAmount in the baseline.")
    mean: float
    stddev: float
    stddev_type: Literal["population"] = "population"


class CategoryOutlierIndicator(BaseModel):
    pw_number: int | None
    applicant_id: str | None
    disaster_number: int | None
    state: str | None
    county: str | None
    application_title: str | None
    damage_category_code: str | None
    project_amount: float
    sigma_above_mean: float


class CategoryOutlierResult(BaseModel):
    indicators: list[CategoryOutlierIndicator]
    page: Page
    category_stats: CategoryStats
    data_scope: DataScope
    caveat: str
    provenance: Provenance


class RepeatedWorksheetGroup(BaseModel):
    applicant_id: str
    disaster_number: int
    state: str | None
    damage_category_code: str
    title_pattern: str = Field(description="Title after removing case, punctuation, and standalone numbers.")
    match_type: Literal["same_wording", "numbered_series"] = Field(
        description=(
            "same_wording: titles identical except case or punctuation (closest match). "
            "numbered_series: titles differ only by numbers, e.g. Site 1 / Site 2 (often legitimate)."
        )
    )
    worksheet_count: int
    pw_numbers: list[int]
    application_titles: list[str] = Field(description="Distinct titles in the group, first 10.")
    distinct_title_count: int
    total_federal_share_obligated: float


class RepeatedWorksheetResult(BaseModel):
    groups: list[RepeatedWorksheetGroup]
    page: Page
    data_scope: DataScope
    caveat: str
    provenance: Provenance


class CostShareIndicator(BaseModel):
    pw_number: int | None
    applicant_id: str | None
    disaster_number: int | None
    state: str | None
    total_obligated: float
    federal_share_obligated: float
    federal_share_ratio: float
    position: Literal["below_band", "above_band"]


class CostShareResult(BaseModel):
    indicators: list[CostShareIndicator]
    page: Page
    policy_context: str
    data_scope: DataScope
    caveat: str
    provenance: Provenance


class QueueReason(BaseModel):
    indicator: IndicatorType
    detail: str = Field(description="Why this indicator applies, with the computed value.")


class ReviewQueueEntry(BaseModel):
    rank: int
    pw_number: int
    applicant_id: str
    disaster_number: int
    application_title: str | None
    damage_category_code: str | None
    project_amount: float | None
    indicator_count: int
    reasons: list[QueueReason]


class ReviewQueueResult(BaseModel):
    queue: list[ReviewQueueEntry]
    total_worksheets_with_indicators: int
    indicator_totals: dict[str, int]
    data_scope: DataScope
    caveat: str
    provenance: Provenance


class MethodologyCard(BaseModel):
    indicator: IndicatorType
    name: str
    question_answered: str
    calculation: str
    default_thresholds: str
    how_to_read: str
    limitations: str
    not_for: str


class SourceRecord(BaseModel):
    pw_number: int | None
    applicant_id: str | None
    disaster_number: int | None
    state: str | None
    county: str | None
    application_title: str | None
    damage_category_code: str | None
    project_size: str | None
    project_amount: float | None
    total_obligated: float | None
    federal_share_obligated: float | None
    declaration_date: str | None


class IndicatorCheck(BaseModel):
    """Re-computation of the triggering indicator for this one worksheet."""

    indicator_met: bool
    measured_value: str
    threshold: str
    baseline: str


class EvidenceBrief(BaseModel):
    pw_number: int
    disaster_number: int
    applicant_id: str
    indicator: IndicatorType
    source_records: list[SourceRecord]
    indicator_check: IndicatorCheck
    methodology: MethodologyCard
    analyst_next_steps: list[str]
    review_status: str
    caveat: str
    provenance: Provenance
