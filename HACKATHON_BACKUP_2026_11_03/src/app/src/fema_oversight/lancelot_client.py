"""Client for the Lancelot Beta MCP server.

Calls run as THIS app's service principal (OAuth M2M via databricks-sdk).
The signed-in user's token (x-forwarded-access-token) is never forwarded.
The bearer token is never logged, returned or stored.

Lancelot is BETA and keeps inputs in its trace logs for 30 days: send only
synthetic or public data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

LANCELOT_URL = os.getenv(
    "LANCELOT_URL", "https://mcp-lancelot-beta-7474654188777746.aws.databricksapps.com"
).rstrip("/")
TIMEOUT_SECONDS = 150.0  # a diagram can take ~70 s; keep well above that
MAX_FILE_BYTES = 14 * 1024 * 1024

log = logging.getLogger("fema_oversight.lancelot")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(_h)
log.setLevel(logging.INFO)
log.propagate = False


class LancelotError(RuntimeError):
    """A call to Lancelot failed (transport or protocol)."""


class LancelotAccessError(LancelotError):
    """Lancelot rejected this app's service principal (401/403/login redirect)."""


ACCESS_MESSAGE = (
    "Lancelot rejected this app's service principal (HTTP {code}). Ask "
    "tom.jacobson@hq.dhs.gov to grant 'Can Use' on mcp-lancelot-beta to the "
    "service principal of app 2026h."
)


def _service_principal_headers() -> dict[str, str]:
    """Authorization header for this app's service principal. Never logged."""
    from databricks.sdk import WorkspaceClient

    headers = WorkspaceClient().config.authenticate()
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise LancelotError("App service principal credentials are unavailable.")
    return {"Authorization": auth}


async def _with_session(fn: Callable[[ClientSession], Awaitable[Any]]) -> Any:
    """Open a new stateless session: initialize, run fn, close."""
    codes: list[int] = []

    async def _record(response: httpx2.Response) -> None:
        codes.append(response.status_code)

    headers = await asyncio.to_thread(_service_principal_headers)
    timeout = httpx2.Timeout(TIMEOUT_SECONDS, connect=30.0)
    try:
        async with httpx2.AsyncClient(
            headers=headers, timeout=timeout, event_hooks={"response": [_record]}
        ) as http:
            async with streamable_http_client(
                LANCELOT_URL + "/mcp", http_client=http, terminate_on_close=False
            ) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(
                    read, write, read_timeout_seconds=TIMEOUT_SECONDS
                ) as session:
                    await session.initialize()
                    return await fn(session)
    except Exception as exc:  # includes ExceptionGroup from the transport
        denied = [c for c in codes if c in (401, 403) or 300 <= c < 400]
        if denied:
            log.warning("lancelot access denied http=%s", denied[0])
            raise LancelotAccessError(ACCESS_MESSAGE.format(code=denied[0])) from None
        log.warning("lancelot call failed: %s", type(exc).__name__)
        raise LancelotError(f"Lancelot call failed ({type(exc).__name__}).") from None


def _parse_result(result: Any) -> dict[str, Any]:
    """Turn a CallToolResult into plain JSON-safe parts, in server order."""
    out: dict[str, Any] = {
        "isError": bool(getattr(result, "is_error", False)),
        "texts": [],
        "json": None,
        "images": [],
        "html": [],
        "structuredContent": getattr(result, "structured_content", None),
    }
    for item in getattr(result, "content", None) or []:
        kind = getattr(item, "type", "")
        if kind == "text":
            text = item.text
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                out["json"] = parsed
            else:
                out["texts"].append(text)
        elif kind == "image":
            out["images"].append({"mimeType": item.mime_type, "data": item.data})
        elif kind == "resource":
            res = item.resource
            text = getattr(res, "text", None)
            if text is not None and (res.mime_type or "").startswith("text/html"):
                out["html"].append({"uri": str(res.uri), "html": text})
    if out["json"] is None and isinstance(out["structuredContent"], dict):
        out["json"] = out["structuredContent"]
    return out


def _log_result(tool: str, parsed: dict[str, Any], elapsed: float) -> None:
    info = parsed.get("json") or {}
    log.info(
        "lancelot tool=%s runId=%s status=%s isError=%s errorCode=%s elapsed_s=%.1f",
        tool,
        info.get("runId"),
        info.get("status"),
        parsed.get("isError"),
        info.get("errorCode"),
        elapsed,
    )


async def list_tools() -> list[dict[str, Any]]:
    async def run(session: ClientSession):
        result = await session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in result.tools
        ]

    tools = await _with_session(run)
    log.info("lancelot tools/list -> %s", [t["name"] for t in tools])
    return tools


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()

    async def run(session: ClientSession):
        return await session.call_tool(
            name, arguments, read_timeout_seconds=TIMEOUT_SECONDS
        )

    parsed = _parse_result(await _with_session(run))
    _log_result(name, parsed, time.perf_counter() - started)
    return parsed


async def generate_diagram(
    *,
    data: str | None = None,
    file_base64: str | None = None,
    file_name: str | None = None,
    diagram_type: str | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    """Send exactly one input: data, or fileBase64 + fileName. No workspacePath."""
    if (data is None) == (file_base64 is None):
        raise ValueError("Provide exactly one of data or file_base64.")
    args: dict[str, Any] = {}
    if data is not None:
        args["data"] = data
    else:
        if not file_name:
            raise ValueError("file_name is required with file_base64.")
        if len(file_base64) * 3 // 4 > MAX_FILE_BYTES:
            raise ValueError("File is larger than 14 MB.")
        args["fileBase64"] = file_base64
        args["fileName"] = file_name
    if diagram_type:
        args["diagramType"] = diagram_type
    if hint:
        args["hint"] = hint
    return await call_tool("generate_diagram", args)


async def generate_choropleth(
    disaster_number: int,
    *,
    pw_number: int | None = None,
    applicant_id: str | None = None,
    sigma_threshold: float | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {"disaster_number": disaster_number}
    if pw_number is not None:
        args["pw_number"] = pw_number
    if applicant_id:
        args["applicant_id"] = applicant_id
    if sigma_threshold is not None:
        args["sigma_threshold"] = sigma_threshold
    if as_of:
        args["as_of"] = as_of
    return await call_tool("generate_choropleth", args)
