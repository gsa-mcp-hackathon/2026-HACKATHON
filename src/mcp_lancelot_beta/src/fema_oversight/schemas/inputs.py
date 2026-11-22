"""Validated request models, one per agent-facing tool.

Every field carries a description written for the model that will fill it in.
Validation happens before any tool code runs, so tools can trust their inputs.
Models forbid unknown fields: a misspelled argument is reported, not ignored.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

StateCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}$"),
    Field(description="Two-letter USPS state or territory code, for example 'LA'."),
]

DisasterNumber = Annotated[
    int,
    Field(ge=1, le=99999, description="FEMA disaster number, for example 4611 for DR-4611."),
]

ApplicantId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_upper=True,
        pattern=r"^[0-9A-Za-z]{3}-[0-9A-Za-z]{5}-[0-9A-Za-z]{2}$",
    ),
    Field(description="FEMA applicant ID exactly as returned by a screening tool, e.g. '109-99109-00'."),
]


class DamageCategory(StrEnum):
    """FEMA Public Assistance damage categories (category of work)."""

    A = "A"  # Debris Removal
    B = "B"  # Emergency Protective Measures
    C = "C"  # Roads and Bridges
    D = "D"  # Water Control Facilities
    E = "E"  # Public Buildings and Contents
    F = "F"  # Public Utilities
    G = "G"  # Parks, Recreational and Other Facilities


class IndicatorType(StrEnum):
    """The review indicators this server can compute and explain."""

    CATEGORY_OUTLIER = "category_outlier"
    REPEATED_WORKSHEET = "repeated_worksheet"
    COST_SHARE_RATIO = "cost_share_ratio"


class _Request(BaseModel):
    """Shared configuration: strict field names, trimmed strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Paged(_Request):
    limit: int = Field(25, ge=1, le=100, description="Maximum results to return (1-100).")
    offset: int = Field(0, ge=0, description="Results to skip; use next_offset from a previous page.")


class CategoryOutlierRequest(_Paged):
    """Inputs for screen_category_cost_outliers."""

    damage_category_code: DamageCategory = Field(
        description=(
            "PA damage category letter: A Debris, B Emergency Protective Measures, "
            "C Roads and Bridges, D Water Control, E Public Buildings, F Public "
            "Utilities, G Parks and Other."
        )
    )
    state_code: StateCode | None = None
    disaster_number: DisasterNumber | None = None
    sigma_threshold: float = Field(
        3.0,
        ge=1.0,
        le=10.0,
        description="Standard deviations above the category mean required to return a project (1-10).",
    )

    @model_validator(mode="after")
    def _require_scope(self) -> CategoryOutlierRequest:
        if self.state_code is None and self.disaster_number is None:
            raise ValueError("provide state_code, disaster_number, or both to scope the baseline")
        return self


class RepeatedWorksheetRequest(_Paged):
    """Inputs for find_repeated_worksheet_groups."""

    state_code: StateCode | None = None
    disaster_number: DisasterNumber | None = None
    min_repeat_count: int = Field(
        2, ge=2, le=100, description="Minimum worksheets with matching titles to form a group (2 or more)."
    )

    @model_validator(mode="after")
    def _require_scope(self) -> RepeatedWorksheetRequest:
        if self.state_code is None and self.disaster_number is None:
            raise ValueError("provide state_code, disaster_number, or both")
        return self


class CostShareRequest(_Paged):
    """Inputs for screen_cost_share_ratios."""

    state_code: StateCode
    disaster_number: DisasterNumber | None = None
    band_low: float = Field(0.70, ge=0.0, le=1.0, description="Lower edge of the expected federal-share ratio.")
    band_high: float = Field(0.95, ge=0.0, le=1.0, description="Upper edge of the expected federal-share ratio.")
    min_total_obligated: float = Field(
        100_000.0, ge=0.0, le=1e12, description="Ignore projects with total obligated below this dollar amount."
    )

    @model_validator(mode="after")
    def _band_order(self) -> CostShareRequest:
        if self.band_low > self.band_high:
            raise ValueError("band_low must be less than or equal to band_high")
        return self


class ReviewQueueRequest(_Request):
    """Inputs for build_review_queue."""

    state_code: StateCode
    disaster_number: DisasterNumber
    limit: int = Field(25, ge=1, le=100, description="Maximum queue entries to return (1-100).")


class ExplainIndicatorRequest(_Request):
    """Inputs for explain_review_indicator."""

    indicator: IndicatorType = Field(
        description="Indicator to explain: category_outlier, repeated_worksheet, or cost_share_ratio."
    )


class EvidenceBriefRequest(_Request):
    """Inputs for prepare_evidence_brief."""

    pw_number: int = Field(ge=1, description="Project Worksheet number from a screening result.")
    disaster_number: DisasterNumber
    indicator: IndicatorType = Field(description="Indicator that put this worksheet in front of the analyst.")
    applicant_id: ApplicantId | None = None
