"""The review rules, as pure functions over plain record dictionaries.

No I/O, no MCP, no Pydantic: each function takes OpenFEMA-shaped records and
returns computed results. This keeps the arithmetic easy to read, easy to unit
test, and easy to compare against the independent SQLite controls in ``eval/``.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fema_oversight.data_access import to_number

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------- category outliers
@dataclass(frozen=True)
class CategoryBaseline:
    n: int
    mean: float
    stddev: float


def category_baseline(records: list[dict[str, Any]]) -> CategoryBaseline | None:
    """Mean and population stddev of projectAmount; None if not computable."""
    amounts = [a for a in (to_number(r.get("projectAmount")) for r in records) if a is not None]
    if len(amounts) < 2:
        return None
    stddev = statistics.pstdev(amounts)
    if stddev <= 0:
        return None
    return CategoryBaseline(n=len(amounts), mean=statistics.fmean(amounts), stddev=stddev)


def category_outliers(
    records: list[dict[str, Any]], baseline: CategoryBaseline, sigma_threshold: float
) -> list[tuple[dict[str, Any], float, float]]:
    """(record, amount, sigma) for records at or above the threshold, highest first."""
    hits = []
    for record in records:
        amount = to_number(record.get("projectAmount"))
        if amount is None:
            continue
        sigma = (amount - baseline.mean) / baseline.stddev
        if sigma >= sigma_threshold:
            hits.append((record, amount, sigma))
    hits.sort(key=lambda hit: (-hit[2], hit[0].get("pwNumber") or 0))
    return hits


# ---------------------------------------------------------------- repeated worksheets
def title_pattern(title: Any) -> str:
    """Comparable title: lowercase words, punctuation and standalone numbers removed.

    "Naples Access to Beach - 3" and "naples access to beach #4" both become
    "naples access to beach". A title made only of numbers becomes "".
    """
    if not isinstance(title, str):
        return ""
    words = _NON_ALNUM.sub(" ", title.lower()).split()
    return " ".join(word for word in words if not word.isdigit())


def _wording(title: str) -> str:
    """Title with case and punctuation removed but numbers kept."""
    return " ".join(_NON_ALNUM.sub(" ", title.lower()).split())


@dataclass
class RepeatGroup:
    disaster_number: int
    applicant_id: str
    title_pattern: str
    damage_category_code: str
    records: list[dict[str, Any]]

    @property
    def titles(self) -> list[str]:
        return sorted({str(r.get("applicationTitle")) for r in self.records})

    @property
    def match_type(self) -> str:
        """same_wording if titles differ only by case/punctuation, else numbered_series."""
        return "same_wording" if len({_wording(t) for t in self.titles}) == 1 else "numbered_series"

    @property
    def federal_share_total(self) -> float:
        return round(sum(to_number(r.get("federalShareObligated")) or 0.0 for r in self.records), 2)


def repeated_worksheet_groups(records: list[dict[str, Any]], min_repeat_count: int) -> list[RepeatGroup]:
    """Groups of >= min_repeat_count worksheets sharing disaster, applicant, pattern, category.

    Ordered closest-match first: same_wording, then larger groups, then larger dollars.
    """
    buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        pattern = title_pattern(record.get("applicationTitle"))
        key = (
            record.get("disasterNumber"),
            record.get("applicantId"),
            pattern,
            record.get("damageCategoryCode"),
        )
        if pattern and all(part is not None for part in key):
            buckets[key].append(record)
    groups = [RepeatGroup(*key, records=rows) for key, rows in buckets.items() if len(rows) >= min_repeat_count]
    groups.sort(
        key=lambda g: (
            g.match_type != "same_wording",
            -len(g.records),
            -g.federal_share_total,
            g.applicant_id,
            g.title_pattern,
        )
    )
    return groups


# ---------------------------------------------------------------- cost share
NORMAL_FEDERAL_SHARE = 0.75


def cost_share_outside_band(
    records: list[dict[str, Any]], band_low: float, band_high: float, min_total_obligated: float
) -> list[tuple[dict[str, Any], float, float, float]]:
    """(record, total, federal, ratio) for ratios strictly outside [band_low, band_high]."""
    hits = []
    for record in records:
        total = to_number(record.get("totalObligated"))
        federal = to_number(record.get("federalShareObligated"))
        if total is None or federal is None or total <= 0 or total < min_total_obligated:
            continue
        ratio = federal / total
        if ratio < band_low or ratio > band_high:
            hits.append((record, total, federal, ratio))
    hits.sort(key=lambda hit: (-abs(hit[3] - NORMAL_FEDERAL_SHARE), hit[0].get("pwNumber") or 0))
    return hits
