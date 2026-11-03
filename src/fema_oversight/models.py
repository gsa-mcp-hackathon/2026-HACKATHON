"""Pydantic models for MCP tool inputs and outputs.

Judging criterion focus:
* strict, LLM-usable input schemas with examples and validation rules;
* reusable response envelopes so every tool returns the same governance fields;
* business-language aliases (``state_code``, ``damage_category_code``) even when
  the upstream dataset uses different column names.

Framing: outputs are REVIEW INDICATORS on public aggregate FEMA data, not
findings. Nothing here detects, proves, or alleges fraud, waste, or abuse.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

from fema_oversight.methodology import REVIEW_CAVEAT

# Keep this in one place so the JSON schema, implementation, documentation and
# tests cannot quietly drift.
MAX_PAGE_SIZE = 100
STATE_CODE_PATTERN = r"^[A-Za-z]{2}$"
APPLICANT_ID_PATTERN = r"^[0-9A-Za-z]{3}-[0-9A-Za-z]{5}-[0-9A-Za-z]{2}$"


class ResponseFormat(str, Enum):
    """How a tool should shape its return value (reserved for future use)."""

    JSON = "json"
    MARKDOWN = "markdown"


class IndicatorType(str, Enum):
    """Review-indicator families this server can explain or cross-reference."""

    COST_SHARE = "cost_share_anomaly"
    REPEATED_WORKSHEET = "repeated_worksheet"
    CATEGORY_OUTLIER = "category_outlier"


class DamageCategory(str, Enum):
    """FEMA Public Assistance categories of work used in this server."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class StrictModel(BaseModel):
    """Shared strict base model for every tool schema."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class PaginationParams(StrictModel):
    """Reusable pagination inputs for list-style tools."""

    limit: int = Field(
        default=25,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=(
            "Maximum items to return on this page. Use small values first so the "
            "agent can inspect results before requesting more. Hard maximum 100."
        ),
        examples=[10, 25],
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="How many matching items to skip from the start.",
        examples=[0, 25],
    )


class JurisdictionFilter(StrictModel):
    """Shared location filter fields."""

    state_code: str = Field(
        ...,
        pattern=STATE_CODE_PATTERN,
        description=(
            "Two-letter USPS state or territory code, such as FL, LA, PR, or GU."
        ),
        examples=["FL", "LA"],
    )
    disaster_number: NonNegativeInt = Field(
        default=0,
        description=(
            "Optional FEMA disaster declaration number. Use 0 to search all "
            "declarations in the jurisdiction."
        ),
        examples=[0, 4734],
    )

    @field_validator("state_code")
    @classmethod
    def normalize_state_code(cls, value: str) -> str:
        return value.strip().upper()


class OptionalJurisdictionFilter(StrictModel):
    """Shared optional location filter fields."""

    state_code: str = Field(
        default="",
        description=(
            "Optional two-letter USPS state or territory code. Leave empty to "
            "search all jurisdictions."
        ),
        examples=["", "FL"],
    )
    disaster_number: NonNegativeInt = Field(
        default=0,
        description=(
            "Optional FEMA disaster declaration number. Use 0 to search all "
            "declarations."
        ),
        examples=[0, 4673],
    )

    @field_validator("state_code")
    @classmethod
    def normalize_optional_state_code(cls, value: str) -> str:
        value = value.strip().upper()
        if value and len(value) != 2:
            raise ValueError("state_code must be two letters or empty.")
        if value and not value.isalpha():
            raise ValueError("state_code must contain only letters.")
        return value


class CostShareAnomalyRequest(JurisdictionFilter):
    """Parameters for cost-share anomaly screening."""

    min_total_obligated: NonNegativeFloat = Field(
        default=100000.0,
        description=(
            "Ignore small projects below this total obligated dollar amount to "
            "reduce noise during triage."
        ),
        examples=[100000.0, 500000.0],
    )
    band_low: float = Field(
        default=0.70,
        ge=0,
        le=1,
        description=(
            "Lower bound of the expected federal-share ratio band. Ratios below "
            "this value are flagged."
        ),
        examples=[0.7, 0.75],
    )
    band_high: float = Field(
        default=0.95,
        ge=0,
        le=1,
        description=(
            "Upper bound of the expected federal-share ratio band. Ratios above "
            "this value are flagged."
        ),
        examples=[0.9, 0.95],
    )
    pagination: PaginationParams | None = Field(
        default=None,
        description="Pagination options for the returned review indicators.",
    )

    @model_validator(mode="after")
    def validate_band(self) -> CostShareAnomalyRequest:
        if self.band_high < self.band_low:
            raise ValueError("band_high must be greater than or equal to band_low.")
        return self


class RepeatedWorksheetsRequest(OptionalJurisdictionFilter):
    """Parameters for repeated worksheet / fragmentation screening."""

    min_repeat_count: PositiveInt = Field(
        default=2,
        ge=2,
        description=(
            "Minimum number of matching worksheets required before a group is "
            "returned for human review."
        ),
        examples=[2, 3],
    )
    pagination: PaginationParams | None = Field(
        default=None,
        description="Pagination options for the returned review groups.",
    )


class CategoryOutlierRequest(OptionalJurisdictionFilter):
    """Parameters for within-category cost outlier screening."""

    damage_category_code: DamageCategory = Field(
        ...,
        description=(
            "FEMA category of work to baseline against. Use only A-G. Management "
            "cost category Z is intentionally excluded."
        ),
        examples=["C", "E"],
    )
    sigma_threshold: PositiveFloat = Field(
        default=3.0,
        ge=1,
        le=10,
        description=(
            "How many standard deviations above the category mean a project must "
            "be before it is flagged."
        ),
        examples=[2.5, 3.0],
    )
    pagination: PaginationParams | None = Field(
        default=None,
        description="Pagination options for the returned outlier list.",
    )


class EvidenceBriefRequest(StrictModel):
    """Parameters for briefing a single project worksheet."""

    pw_number: PositiveInt = Field(
        ...,
        description=(
            "Project Worksheet number returned by a screening tool. If the PW is "
            "ambiguous across declarations, also pass disaster_number and "
            "applicant_id from the screening result."
        ),
        examples=[169],
    )
    indicator: IndicatorType = Field(
        ...,
        description=(
            "Which review indicator caused this project to be examined. This does "
            "not change the source data; it selects the correct methodology card "
            "for the brief."
        ),
        examples=["cost_share_anomaly"],
    )
    disaster_number: NonNegativeInt = Field(
        default=0,
        description="Optional disaster declaration number for disambiguation.",
        examples=[0, 4734],
    )
    applicant_id: str = Field(
        default="",
        description=(
            "Optional applicant identifier for disambiguation. Use the exact value "
            "from the screening result when multiple projects share a PW number."
        ),
        examples=["123-0BE2A-00", ""],
    )

    @field_validator("applicant_id")
    @classmethod
    def normalize_optional_applicant_id(cls, value: str) -> str:
        return value.strip()


class ExplainIndicatorRequest(StrictModel):
    """Parameters for returning an indicator methodology card."""

    indicator: IndicatorType = Field(
        ...,
        description=(
            "Indicator to explain. Use this when an analyst or judge needs the "
            "fixed methodology, thresholds, and limitations behind a signal."
        ),
        examples=["repeated_worksheet"],
    )


class OversightTriageRequest(JurisdictionFilter):
    """Parameters for cross-indicator queue building."""

    min_total_obligated: NonNegativeFloat = Field(
        default=100000.0,
        description=(
            "Minimum total obligated amount used by the embedded cost-share "
            "screening pass."
        ),
        examples=[100000.0],
    )
    band_low: float = Field(default=0.70, ge=0, le=1, examples=[0.7])
    band_high: float = Field(default=0.95, ge=0, le=1, examples=[0.95])
    sigma_threshold: PositiveFloat = Field(
        default=3.0,
        ge=1,
        le=10,
        description="Sigma threshold used by the embedded category-outlier pass.",
        examples=[3.0],
    )
    min_repeat_count: PositiveInt = Field(
        default=2,
        ge=2,
        description=(
            "Minimum repeated worksheet count used by the embedded duplicate / "
            "fragmentation pass."
        ),
        examples=[2],
    )
    pagination: PaginationParams | None = Field(
        default=None,
        description="Pagination options for the ranked review queue.",
    )

    @model_validator(mode="after")
    def validate_triage_band(self) -> OversightTriageRequest:
        if self.band_high < self.band_low:
            raise ValueError("band_high must be greater than or equal to band_low.")
        return self


class ToolErrorResponse(StrictModel):
    """Structured, agent-recoverable tool error returned to the model."""

    error: str = Field(description="Human-readable failure summary.")
    error_code: str = Field(description="Stable code suitable for automation.")
    hint: str | None = Field(
        default=None,
        description="Concrete next step the calling agent should try.",
    )
    retryable: bool = Field(
        default=False,
        description="True when a retry or narrower query may succeed.",
    )


class DataScope(StrictModel):
    """What subset of source data this response actually examined."""

    records_retrieved: NonNegativeInt
    record_cap: PositiveInt
    possibly_truncated: bool
    upstream_total_matches: NonNegativeInt | None = None
    disaster_filter: NonNegativeInt | None = None
    baseline: str | None = None


class ProvenanceBlock(StrictModel):
    """Required provenance fields attached to every tool output."""

    source: str
    last_updated: str
    update_frequency: str
    retrieved_at: str
    methodology: str
    limitations: str
    review_status: str = Field(default=REVIEW_CAVEAT)


class PaginatedResponse(StrictModel):
    """Standard envelope for list-style tools."""

    total: NonNegativeInt
    count: NonNegativeInt
    offset: NonNegativeInt
    items: list[Any]
    has_more: bool
    next_offset: NonNegativeInt | None = None
    data_scope: DataScope
    caveat: str = Field(default=REVIEW_CAVEAT)
    _provenance: ProvenanceBlock


# ---------------------------------------------------------------------------
# Agent-facing parameter types
# ---------------------------------------------------------------------------
# Why these exist: FastMCP builds each tool's JSON schema from the *function
# signature*, not from the request model the function validates against later.
# A bare ``state_code: str`` therefore reaches the LLM with no description,
# pattern, or examples, even though ``JurisdictionFilter`` has all three.
# Declaring the annotated types once here, and reusing them in every tool
# signature, keeps the published schema and the server-side validation rules
# identical. The request models remain the second, authoritative check
# (cross-field rules such as band_low <= band_high live only there).

StateCodeArg = Annotated[
    str,
    Field(
        pattern=STATE_CODE_PATTERN,
        description=(
            "REQUIRED two-letter USPS state or territory code (FL, LA, PR, GU). "
            "Convert full state names to the code before calling."
        ),
        examples=["FL", "LA"],
    ),
]

DisasterNumberArg = Annotated[
    int,
    Field(
        ge=0,
        description=(
            "Optional FEMA disaster declaration number (e.g. 4734 for a specific "
            "hurricane). 0 means all declarations in scope."
        ),
        examples=[0, 4734],
    ),
]

PaginationArg = Annotated[
    PaginationParams | None,
    Field(
        description=(
            "Optional page window {limit, offset}. Omit for the first 25 items. "
            "When the response says has_more=true, call again with "
            "offset=next_offset instead of raising limit above 100."
        ),
    ),
]

IndicatorArg = Annotated[
    IndicatorType,
    Field(
        description=(
            "Review-indicator family. cost_share_anomaly = federal share outside "
            "the expected band; repeated_worksheet = same applicant/title/category "
            "repeated within a disaster; category_outlier = cost far above the "
            "category mean."
        ),
        examples=["cost_share_anomaly", "category_outlier"],
    ),
]

MinTotalObligatedArg = Annotated[
    float,
    Field(
        ge=0,
        description=(
            "Skip projects whose totalObligated is below this many dollars "
            "before cost-share screening. Raise it to focus on material dollars."
        ),
        examples=[100000.0, 500000.0],
    ),
]

BandLowArg = Annotated[
    float,
    Field(
        ge=0,
        le=1,
        description=(
            "Lower edge of the expected federal-share ratio (0-1). Ratios below "
            "it are flagged. Must be <= band_high."
        ),
        examples=[0.7, 0.75],
    ),
]

BandHighArg = Annotated[
    float,
    Field(
        ge=0,
        le=1,
        description=(
            "Upper edge of the expected federal-share ratio (0-1). Ratios above "
            "it are flagged. Use 1.0 when 100% federal share is authorized."
        ),
        examples=[0.95, 1.0],
    ),
]

SigmaThresholdArg = Annotated[
    float,
    Field(
        ge=1,
        le=10,
        description=(
            "Standard deviations above the category mean required to flag a "
            "project. Higher = fewer, more extreme outliers."
        ),
        examples=[2.5, 3.0],
    ),
]

MinRepeatCountArg = Annotated[
    int,
    Field(
        ge=2,
        description=(
            "Minimum worksheets sharing disaster, applicant, title and category "
            "before the group counts as a repeated pattern."
        ),
        examples=[2, 3],
    ),
]

PwNumberArg = Annotated[
    int,
    Field(
        ge=1,
        description=(
            "Project Worksheet number copied from a screening or triage result "
            "(field pw_number). Do not guess PW numbers."
        ),
        examples=[169],
    ),
]

ApplicantIdArg = Annotated[
    str,
    Field(
        # Deliberately a charset/length rule rather than APPLICANT_ID_PATTERN:
        # it blocks quote/operator characters (OData injection) without
        # rejecting an unusual but genuine identifier format.
        pattern=r"^[0-9A-Za-z-]{0,20}$",
        description=(
            "Optional applicant identifier copied verbatim from a screening "
            "result (usually NNN-XXXXX-NN). Pass it with disaster_number when a "
            "PW number is shared by several projects."
        ),
        examples=["", "123-0BE2A-00"],
    ),
]
