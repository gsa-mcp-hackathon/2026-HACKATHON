"""Shared fixtures: small hand-built record sets with known answers."""

from __future__ import annotations

import pytest

from fema_oversight.data_access import SnapshotSource
from fema_oversight.server import build_server


def record(
    pw,
    amount,
    *,
    applicant="001-00001-00",
    title="Main Street Bridge",
    category="C",
    total=None,
    federal=None,
    disaster=4673,
    state="FL",
):
    total = amount if total is None else total
    return {
        "pwNumber": pw,
        "applicantId": applicant,
        "stateAbbreviation": state,
        "county": "Lee County",
        "disasterNumber": disaster,
        "applicationTitle": title,
        "damageCategoryCode": category,
        "projectSize": "Large",
        "projectAmount": amount,
        "totalObligated": total,
        "federalShareObligated": total * 0.75 if federal is None else federal,
        "declarationDate": "2022-09-29T00:00:00.000Z",
        "lastRefresh": "2026-11-01T00:00:00.000Z",
    }


@pytest.fixture
def records():
    """20 ordinary category C projects at $100k plus one at $5M (a clear outlier),
    a same-wording pair, a numbered series, and two cost-share cases."""
    rows = [record(pw, 100_000.0, title=f"Culvert {pw}", applicant=f"001-{pw:05d}-00") for pw in range(1, 21)]
    rows.append(record(100, 5_000_000.0, title="Hollandtown Road Bridge"))
    rows.append(record(101, 120_000.0, title="Div 13 Yancey", applicant="002-00002-00", category="A"))
    rows.append(record(102, 130_000.0, title="DIV 13 - Yancey", applicant="002-00002-00", category="A"))
    rows += [
        record(110 + i, 50_000.0, title=f"Beach Access {i}", applicant="003-00003-00", category="G")
        for i in range(1, 4)
    ]
    rows.append(record(200, 400_000.0, title="EOC", applicant="004-00004-00", category="B", federal=400_000.0))
    rows.append(record(201, 400_000.0, title="Shelter", applicant="004-00004-00", category="B", federal=200_000.0))
    return rows


@pytest.fixture
def source(records):
    return SnapshotSource(records, retrieved_at="2026-11-18T00:00:00+00:00")


@pytest.fixture
def server(source):
    return build_server(source)
