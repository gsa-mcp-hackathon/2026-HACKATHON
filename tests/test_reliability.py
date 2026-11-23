"""Reliability controls for retry, cache, and content-free telemetry behavior."""

from __future__ import annotations

import asyncio

import httpx
from fastmcp import Client

from fema_oversight.data_access import CachingRecordSource, FetchResult, OpenFEMASource, PAQuery
from fema_oversight.observability import telemetry
from fema_oversight.server import build_server
from tests.conftest import record

QUERY = PAQuery(fields=("pwNumber",), record_cap=10, state_code="FL")


async def _no_sleep(_: float) -> None:
    return None


async def test_retry_recovers_from_transient_upstream_failure() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"PublicAssistanceFundedProjectsDetails": [{"pwNumber": 7}]})

    source = OpenFEMASource(
        transport=httpx.MockTransport(handler), retry_attempts=3, retry_delay_seconds=0, sleep=_no_sleep
    )
    result = await source.fetch(QUERY)
    assert calls == 3 and result.records == [{"pwNumber": 7}]


async def test_cache_coalesces_concurrent_identical_queries() -> None:
    class CountingSource:
        calls = 0

        async def fetch(self, query: PAQuery) -> FetchResult:
            self.calls += 1
            await asyncio.sleep(0)
            return FetchResult(records=[{"pwNumber": 1}], record_cap=query.record_cap)

    inner = CountingSource()
    source = CachingRecordSource(inner, ttl_seconds=60)
    first, second = await asyncio.gather(source.fetch(QUERY), source.fetch(QUERY))
    third = await source.fetch(QUERY)
    assert inner.calls == 1
    assert first is second is third


async def test_tool_metrics_record_counts_without_request_content() -> None:
    sensitive_title = "do-not-retain-this-title"
    server = build_server(
        source=type(
            "StaticSource",
            (),
            {"fetch": lambda self, query: _result(record(1, 100_000, title=sensitive_title), query)},
        )()
    )
    async with Client(server) as client:
        await client.call_tool("explain_review_indicator", {"params": {"indicator": "category_outlier"}})
        resources = await client.read_resource("fema-pa://metrics")
    text = resources[0].text
    assert "explain_review_indicator" in text
    assert sensitive_title not in text
    assert telemetry.snapshot()["tools"]["explain_review_indicator"]["invocations"] >= 1


async def _result(row: dict, query: PAQuery) -> FetchResult:
    return FetchResult(records=[row], record_cap=query.record_cap)
