"""Every failure reaches the agent as an actionable MCP error, never a stack trace."""

import httpx
import pytest
from fastmcp import Client

from fema_oversight.data_access import MAX_RESPONSE_BYTES, OpenFEMASource, PAQuery, SnapshotSource
from fema_oversight.errors import ErrorCode, ReviewToolError
from fema_oversight.server import build_server
from tests.conftest import record


async def error_text(server, name, **params):
    async with Client(server) as client:
        result = await client.call_tool(name, {"params": params}, raise_on_error=False)
    assert result.is_error, f"{name} should have failed"
    return result.content[0].text


@pytest.mark.parametrize(
    ("name", "params", "expected"),
    [
        ("screen_category_cost_outliers", {"damage_category_code": "Z", "state_code": "FL"}, "damage_category_code"),
        ("screen_category_cost_outliers", {"damage_category_code": "C"}, "provide state_code"),
        ("screen_cost_share_ratios", {"state_code": "FLA"}, "state_code"),
        ("screen_cost_share_ratios", {"state_code": "FL", "band_low": 0.9, "band_high": 0.5}, "band_low"),
        ("find_repeated_worksheet_groups", {"state_code": "FL", "bogus": 1}, "Extra inputs"),
        (
            "prepare_evidence_brief",
            {"pw_number": 0, "disaster_number": 4673, "indicator": "category_outlier"},
            "pw_number",
        ),
        ("explain_review_indicator", {"indicator": "fraud_score"}, "indicator"),
    ],
)
async def test_invalid_arguments_name_the_field(server, name, params, expected):
    assert expected in await error_text(server, name, **params)


async def test_not_found(server):
    text = await error_text(
        server, "prepare_evidence_brief", pw_number=9999, disaster_number=4673, indicator="category_outlier"
    )
    assert text.startswith("[NOT_FOUND]") and "Retryable: no" in text


async def test_ambiguous_worksheet_lists_applicants():
    rows = [record(7, 1.0, applicant="001-00001-00"), record(7, 2.0, applicant="002-00002-00")]
    text = await error_text(
        build_server(SnapshotSource(rows)),
        "prepare_evidence_brief",
        pw_number=7,
        disaster_number=4673,
        indicator="cost_share_ratio",
    )
    assert text.startswith("[AMBIGUOUS_IDENTITY]") and "001-00001-00" in text and "002-00002-00" in text


async def test_insufficient_data(server):
    text = await error_text(server, "screen_category_cost_outliers", damage_category_code="D", state_code="FL")
    assert text.startswith("[INSUFFICIENT_DATA]")


def _source(handler):
    return OpenFEMASource(transport=httpx.MockTransport(handler))


QUERY = PAQuery(fields=("pwNumber",), record_cap=10, state_code="FL")


@pytest.mark.parametrize(
    ("handler", "code", "retryable"),
    [
        (lambda req: httpx.Response(503), ErrorCode.UPSTREAM_UNAVAILABLE, True),
        (lambda req: httpx.Response(429), ErrorCode.UPSTREAM_UNAVAILABLE, True),
        (lambda req: httpx.Response(400), ErrorCode.UPSTREAM_UNAVAILABLE, False),
        (lambda req: httpx.Response(200, content=b"not json"), ErrorCode.UPSTREAM_INVALID_RESPONSE, True),
        (lambda req: httpx.Response(200, json={"metadata": {}}), ErrorCode.UPSTREAM_INVALID_RESPONSE, True),
        (
            lambda req: httpx.Response(200, content=b" " * (MAX_RESPONSE_BYTES + 1)),
            ErrorCode.UPSTREAM_INVALID_RESPONSE,
            False,
        ),
    ],
)
async def test_upstream_failures_are_sanitized(handler, code, retryable):
    with pytest.raises(ReviewToolError) as caught:
        await _source(handler).fetch(QUERY)
    assert caught.value.code is code and caught.value.retryable is retryable
    assert "fema.gov" not in caught.value.agent_message()


async def test_timeout_is_retryable():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ReviewToolError) as caught:
        await _source(slow).fetch(QUERY)
    assert caught.value.code is ErrorCode.UPSTREAM_UNAVAILABLE and caught.value.retryable


async def test_request_uses_fixed_origin_and_filter():
    seen = {}

    def handler(request):
        seen["url"] = request.url
        return httpx.Response(200, json={"PublicAssistanceFundedProjectsDetails": [{"pwNumber": 1}]})

    result = await _source(handler).fetch(
        PAQuery(fields=("pwNumber",), record_cap=99999, state_code="FL", disaster_number=4673)
    )
    assert (
        seen["url"].host == "www.fema.gov" and seen["url"].path == "/api/open/v2/PublicAssistanceFundedProjectsDetails"
    )
    assert seen["url"].params["$filter"] == "stateAbbreviation eq 'FL' and disasterNumber eq 4673"
    assert seen["url"].params["$top"] == "10000" and result.record_cap == 10000


async def test_upstream_error_reaches_agent_as_tool_error():
    server = build_server(_source(lambda req: httpx.Response(502)))
    text = await error_text(server, "screen_cost_share_ratios", state_code="FL")
    assert text.startswith("[UPSTREAM_UNAVAILABLE]") and "Retryable: yes" in text


async def test_unexpected_exceptions_are_masked():
    class Broken:
        async def fetch(self, query):
            raise RuntimeError("secret internal path /etc/passwd")

    text = await error_text(build_server(Broken()), "screen_cost_share_ratios", state_code="FL")
    assert "secret" not in text and "/etc/passwd" not in text
