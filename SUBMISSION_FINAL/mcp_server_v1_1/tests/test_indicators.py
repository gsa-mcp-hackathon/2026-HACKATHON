"""The review rules, tested on records with known answers."""

import pytest

from fema_oversight import indicators
from tests.conftest import record


def test_category_outlier_finds_the_planted_project(records):
    category_c = [r for r in records if r["damageCategoryCode"] == "C"]
    baseline = indicators.category_baseline(category_c)
    hits = indicators.category_outliers(category_c, baseline, 3.0)
    assert [r["pwNumber"] for r, _, _ in hits] == [100]
    assert baseline.n == 21
    assert hits[0][2] == pytest.approx((5_000_000 - baseline.mean) / baseline.stddev)


def test_baseline_needs_variation():
    assert indicators.category_baseline([record(1, 10.0), record(2, 10.0)]) is None
    assert indicators.category_baseline([record(1, 10.0)]) is None


def test_string_amounts_are_accepted():
    rows = [{**record(1, 0.0), "projectAmount": "10"}, {**record(2, 0.0), "projectAmount": "30"}]
    baseline = indicators.category_baseline(rows)
    assert baseline.mean == 20.0


@pytest.mark.parametrize(
    ("title", "pattern"),
    [
        ("Naples Access to Beach - 3", "naples access to beach"),
        ("naples access to beach #4", "naples access to beach"),
        ("DIV 13 - Yancey", "div yancey"),
        ("Site 2A", "site 2a"),
        ("123", ""),
        (None, ""),
    ],
)
def test_title_pattern(title, pattern):
    assert indicators.title_pattern(title) == pattern


def test_repeat_groups_rank_same_wording_first(records):
    groups = indicators.repeated_worksheet_groups(records, 2)
    assert [(g.title_pattern, g.match_type, len(g.records)) for g in groups] == [
        ("div yancey", "same_wording", 2),
        ("beach access", "numbered_series", 3),
    ]


def test_cost_share_band_is_strict(records):
    hits = indicators.cost_share_outside_band(records, 0.70, 0.95, 100_000)
    assert sorted(r["pwNumber"] for r, *_ in hits) == [200, 201]
    assert indicators.cost_share_outside_band([record(1, 200_000.0, federal=150_000.0)], 0.75, 0.95, 0) == []


def test_cost_share_skips_small_and_zero_totals():
    rows = [record(1, 0.0, total=0.0, federal=0.0), record(2, 50_000.0, federal=50_000.0)]
    assert indicators.cost_share_outside_band(rows, 0.70, 0.95, 100_000) == []
