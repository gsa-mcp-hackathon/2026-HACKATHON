"""MCP contract: the exact tool set, annotations, and self-describing schemas."""

import pytest
from fastmcp import Client

EXPECTED_TOOLS = {
    "build_review_queue",
    "screen_category_cost_outliers",
    "find_repeated_worksheet_groups",
    "screen_cost_share_ratios",
    "explain_review_indicator",
    "prepare_evidence_brief",
}


@pytest.fixture
async def tools(server):
    async with Client(server) as client:
        return {tool.name: tool for tool in await client.list_tools()}


async def test_exact_tool_set(tools):
    assert set(tools) == EXPECTED_TOOLS


async def test_every_tool_is_read_only(tools):
    for tool in tools.values():
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True


async def test_descriptions_state_when_and_when_not_to_use(tools):
    for tool in tools.values():
        assert "USE WHEN" in tool.description and "DO NOT USE" in tool.description, tool.name


def _fields(schema, defs):
    params = schema["properties"]["params"]
    model = defs[params["$ref"].split("/")[-1]] if "$ref" in params else params
    return model["properties"]


async def test_every_input_field_is_described(tools):
    for tool in tools.values():
        schema = tool.inputSchema
        for name, spec in _fields(schema, schema.get("$defs", {})).items():
            text = spec.get("description") or any("description" in s for s in spec.get("anyOf", []))
            assert text, f"{tool.name}.{name} has no description"


async def test_every_tool_publishes_an_output_schema(tools):
    for tool in tools.values():
        assert tool.outputSchema and tool.outputSchema.get("properties"), tool.name


async def test_resources_and_prompt(server):
    async with Client(server) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        prompts = {p.name for p in await client.list_prompts()}
    assert uris == {"fema-pa://provenance", "fema-pa://methodology", "fema-pa://metrics"}
    assert prompts == {"disaster_review"}
