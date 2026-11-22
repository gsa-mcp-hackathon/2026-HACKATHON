"""Input models reject bad arguments before any tool code runs."""

import pytest
from pydantic import ValidationError

from fema_oversight.schemas.inputs import (
    CategoryOutlierRequest,
    CostShareRequest,
    EvidenceBriefRequest,
    RepeatedWorksheetRequest,
)


def test_state_code_is_normalized():
    assert CostShareRequest(state_code=" la ").state_code == "LA"


@pytest.mark.parametrize("state", ["L", "LAX", "1A", "L'"])
def test_malformed_state_code_rejected(state):
    with pytest.raises(ValidationError):
        CostShareRequest(state_code=state)


@pytest.mark.parametrize("category", ["Z", "CC", "", "c'"])
def test_unknown_damage_category_rejected(category):
    with pytest.raises(ValidationError):
        CategoryOutlierRequest(damage_category_code=category, state_code="FL")


@pytest.mark.parametrize("sigma", [0.5, 10.5])
def test_sigma_out_of_range_rejected(sigma):
    with pytest.raises(ValidationError):
        CategoryOutlierRequest(damage_category_code="C", state_code="FL", sigma_threshold=sigma)


def test_unscoped_screens_rejected():
    with pytest.raises(ValidationError, match="state_code"):
        CategoryOutlierRequest(damage_category_code="C")
    with pytest.raises(ValidationError, match="state_code"):
        RepeatedWorksheetRequest()


def test_band_order_enforced():
    with pytest.raises(ValidationError, match="band_low"):
        CostShareRequest(state_code="FL", band_low=0.9, band_high=0.5)


def test_min_repeat_count_at_least_two():
    with pytest.raises(ValidationError):
        RepeatedWorksheetRequest(state_code="FL", min_repeat_count=1)


@pytest.mark.parametrize("applicant", ["x' or 1 eq 1", "109-99109", "109_99109_00"])
def test_applicant_id_format_blocks_injection(applicant):
    with pytest.raises(ValidationError):
        EvidenceBriefRequest(pw_number=1, disaster_number=4611, indicator="category_outlier", applicant_id=applicant)


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        RepeatedWorksheetRequest(state_code="FL", min_repeats=3)
