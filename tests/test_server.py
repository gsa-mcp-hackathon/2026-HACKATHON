"""Smoke tests for the FEMA Evidence & Oversight Graph MCP server.

Verify the server imports and every submodule registers, that all six
oversight tools are discoverable, and that every published tool schema is
self-describing enough for an LLM to parameterize without guessing.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from fema_oversight.app import mcp
from fema_oversight.config import settings

EXPECTED_TOOLS = {
    "get_cost_share_anomalies",
    "find_repeated_worksheets",
    "detect_category_outliers",
    "explain_risk_indicator",
    "generate_evidence_brief",
    "build_oversight_triage_queue",
}


def test_server_is_importable():
    assert mcp is not None


def test_server_has_name():
    assert mcp.name == "FEMA Evidence & Oversight Graph"


def test_default_transport_is_stdio():
    assert settings.mcp_transport == "stdio"


def test_tools_register_without_error():
    from fema_oversight.tools import register_tools

    register_tools(FastMCP("test"))


def test_prompts_register_without_error():
    from fema_oversight.prompts import register_prompts

    register_prompts(FastMCP("test"))


def test_resources_register_without_error():
    from fema_oversight.resources import register_resources

    register_resources(FastMCP("test"))


def test_routes_register_without_error():
    from fema_oversight.routes import register_routes

    register_routes(FastMCP("test"))


@pytest.mark.asyncio
async def test_all_tools_discoverable():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS, f"diff: {names ^ EXPECTED_TOOLS}"


@pytest.mark.asyncio
async def test_every_tool_parameter_is_described_for_the_llm():
    """Regression guard: a bare ``x: str`` signature publishes an empty schema.

    FastMCP derives the schema from the function signature, so a tool can pass
    every behavioural test while still giving the model no description, bounds
    or examples. This test fails if any parameter loses its description.
    """
    from fastmcp import Client

    async with Client(mcp) as client:
        tools = await client.list_tools()
    undocumented = [
        f"{tool.name}.{param}"
        for tool in tools
        for param, spec in tool.input_schema.get("properties", {}).items()
        if not spec.get("description")
    ]
    assert not undocumented, f"parameters without descriptions: {undocumented}"


@pytest.mark.asyncio
async def test_global_rate_limit_holds_when_session_ids_rotate(monkeypatch):
    """Regression: the in-memory transport mints a new session id per call,
    so a per-session bucket alone never filled up. The process-wide ceiling
    must still refuse the call that exceeds it."""
    from fastmcp import Client

    from fema_oversight.middleware import StructuredErrorsAndRateLimit

    limiter = next(
        m for m in mcp.middleware if isinstance(m, StructuredErrorsAndRateLimit)
    )
    limiter._buckets.clear()
    monkeypatch.setattr(settings, "rate_limit_global_calls_per_minute", 3)
    args = {"indicator": "category_outlier"}
    try:
        async with Client(mcp) as client:
            for _ in range(3):
                ok = await client.call_tool("explain_risk_indicator", args)
                assert "error" not in ok.data
            refused = await client.call_tool("explain_risk_indicator", args)
    finally:
        limiter._buckets.clear()
    assert refused.data["error_code"] == "rate_limit_exceeded"
    assert refused.data["retryable"] is True


@pytest.mark.asyncio
async def test_every_tool_is_annotated_read_only():
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name


@pytest.mark.asyncio
async def test_provenance_resource_registered():
    resources = await mcp.list_resources()
    uris = {str(r.uri) for r in resources}
    assert "fema-pa://provenance" in uris
