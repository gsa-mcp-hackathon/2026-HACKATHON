"""End-to-end tool calls through an in-memory MCP client."""

from fastmcp import Client


async def call(server, name, **params):
    async with Client(server) as client:
        result = await client.call_tool(name, {"params": params}, raise_on_error=False)
    return result


async def test_category_outliers_returns_evidence_chain(server):
    result = await call(server, "screen_category_cost_outliers", damage_category_code="C", state_code="fl")
    data = result.structured_content
    assert not result.is_error
    assert [i["pw_number"] for i in data["indicators"]] == [100]
    assert data["data_scope"] == {
        "records_retrieved": 21,
        "record_cap": 10000,
        "possibly_truncated": False,
        "filters": {"state_code": "FL", "disaster_number": None, "damage_category_code": "C"},
    }
    prov = data["provenance"]
    assert prov["retrieved_at"] == "2026-11-18T00:00:00+00:00"
    assert prov["source_last_refresh"] == "2026-11-01T00:00:00.000Z"
    assert "sigma >= 3.0" in prov["rule"]
    assert prov["review_status"] == "Analyst review required."


async def test_pagination_envelope(server):
    first = (await call(server, "find_repeated_worksheet_groups", state_code="FL", limit=1)).structured_content
    assert first["page"] == {"total": 2, "count": 1, "offset": 0, "has_more": True, "next_offset": 1}
    second = (
        await call(server, "find_repeated_worksheet_groups", state_code="FL", limit=1, offset=1)
    ).structured_content
    assert second["page"]["has_more"] is False and second["page"]["next_offset"] is None
    assert first["groups"][0]["title_pattern"] != second["groups"][0]["title_pattern"]


async def test_cost_share_positions(server):
    data = (await call(server, "screen_cost_share_ratios", state_code="FL")).structured_content
    positions = {i["pw_number"]: i["position"] for i in data["indicators"]}
    assert positions == {200: "above_band", 201: "below_band"}


async def test_review_queue_merges_indicators(server):
    data = (await call(server, "build_review_queue", state_code="FL", disaster_number=4673)).structured_content
    assert data["queue"][0]["pw_number"] == 100
    assert data["indicator_totals"] == {"category_outlier": 1, "repeated_worksheet": 2, "cost_share_ratio": 2}
    assert {e["pw_number"] for e in data["queue"]} >= {100, 101, 102, 200, 201}
    for entry in data["queue"]:
        assert entry["reasons"] and entry["indicator_count"] == len({r["indicator"] for r in entry["reasons"]})


async def test_evidence_brief_rechecks_indicator(server):
    data = (
        await call(server, "prepare_evidence_brief", pw_number=100, disaster_number=4673, indicator="category_outlier")
    ).structured_content
    assert data["indicator_check"]["indicator_met"] is True
    assert data["source_records"][0]["application_title"] == "Hollandtown Road Bridge"
    assert data["methodology"]["indicator"] == "category_outlier"


async def test_evidence_brief_repeat_check(server):
    data = (
        await call(
            server, "prepare_evidence_brief", pw_number=101, disaster_number=4673, indicator="repeated_worksheet"
        )
    ).structured_content
    assert data["indicator_check"]["indicator_met"] is True
    assert "[101, 102]" in data["indicator_check"]["measured_value"]


async def test_explain_needs_no_records(server):
    data = (await call(server, "explain_review_indicator", indicator="repeated_worksheet")).structured_content
    assert data["not_for"].startswith("Testing duplication of benefits")
