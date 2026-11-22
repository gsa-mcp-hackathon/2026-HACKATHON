"""Connection and auth for the mcp-lancelot-beta MCP server.

Auth modes (brief section 4):
  A  signed-in user: the token Databricks Apps forwards in x-forwarded-access-token
  B  this app's own service principal: OAuth M2M token from databricks-sdk

Tokens are passed around only as arguments; they are never logged, stored, or
returned in any result dict.

Written against the official MCP Python SDK 2.3.0 (streamable_http_client +
httpx2). See DECISIONS.md D1.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from client import config

SERVER_BASE = config.SERVER_BASE
MCP_URL = SERVER_BASE + "/mcp"
# Test hook (code review L10): unit tests set an httpx2.ASGITransport here to run the real MCP
# client code against an in-process server. None means the normal network transport.
_TRANSPORT = None
TOOL_NAME = "generate_diagram"
CHOROPLETH_TOOL_NAME = "generate_choropleth"
HTTP_TIMEOUT_S = 130  # one call can take ~70 s; brief requires >= 120 s
CONNECT_TIMEOUT_S = 15

MODE_A = "A-user"
MODE_B = "B-service-principal"


@dataclass
class Auth:
    mode: str  # MODE_A | MODE_B
    token: str  # never log or persist
    caller_email: str | None  # x-forwarded-email (Mode A) or None
    sp_application_id: str | None  # DATABRICKS_CLIENT_ID (Mode B)
    note: str = ""

    def public(self) -> dict:
        """Token-free description for reports and the UI."""
        return {
            "mode": self.mode,
            "callerEmail": self.caller_email,
            "spApplicationId": self.sp_application_id,
            "note": self.note,
        }


def header(headers: Any, name: str) -> str | None:
    """Case-insensitive header lookup on a mapping (st.context.headers or dict)."""
    if not headers:
        return None
    try:
        v = headers.get(name)
        if v is None:
            v = headers.get(name.title())
    except Exception:
        v = None
    if v is None:
        for k in list(headers.keys()):
            if str(k).lower() == name.lower():
                v = headers[k]
                break
    v = (v or "").strip()
    return v or None


_SP_CLIENT = None


def _sp_client():
    """One WorkspaceClient per process (code review L2). The SDK caches the service principal's
    OAuth token and refreshes it only near expiry, so page reruns do not mint new tokens."""
    global _SP_CLIENT
    if _SP_CLIENT is None:
        from databricks.sdk import WorkspaceClient

        _SP_CLIENT = WorkspaceClient()
    return _SP_CLIENT


def service_principal_token() -> tuple[str, str | None]:
    """OAuth token for this app's own service principal (Mode B)."""
    w = _sp_client()
    hdrs = w.config.authenticate()
    authz = hdrs.get("Authorization", "")
    if not authz.lower().startswith("bearer "):
        raise RuntimeError("databricks-sdk did not return a Bearer token for the app service principal")
    return authz[7:], w.config.client_id


# ---------------------------------------------------------------- plain HTTP

def http_get(path: str, token: str, timeout: float = HTTP_TIMEOUT_S) -> dict:
    """GET a server route without following redirects (a 302 means the proxy
    rejected the token). Returns a token-free result dict."""
    t0 = time.monotonic()
    out: dict = {"path": path, "httpStatus": None, "json": None, "bodySnippet": None, "ms": None, "error": None}
    try:
        r = requests.get(
            SERVER_BASE + path,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=(CONNECT_TIMEOUT_S, timeout),
            allow_redirects=False,
        )
        out["httpStatus"] = r.status_code
        if r.status_code in (301, 302, 303, 307, 308):
            out["redirectHost"] = _host_only(r.headers.get("Location", ""))
        try:
            out["json"] = r.json()
        except ValueError:
            out["bodySnippet"] = r.text[:300]
    except Exception as e:  # network error: record, never raise
        out["error"] = f"{type(e).__name__}: {e}"[:500]
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def _host_only(url: str) -> str:
    # Keep only scheme+host of a redirect target; query strings can carry state.
    try:
        from urllib.parse import urlsplit

        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}" if p.netloc else ""
    except Exception:
        return ""


def resolve_auth(headers: Any, probe: Callable[[str, str], dict] = http_get,
                 force_mode_b: bool = False) -> tuple[Auth | None, dict]:
    """Mode A first; fall back to Mode B if no user token is forwarded or the
    server rejects it. force_mode_b skips Mode A entirely (no probe with the
    user token). Returns (auth, finding) where finding is token-free."""
    finding: dict = {"userTokenForwarded": False, "modeAHealth": None, "modeBError": None,
                     "forcedModeB": bool(force_mode_b)}
    user_token = header(headers, "x-forwarded-access-token")
    email = header(headers, "x-forwarded-email")
    if force_mode_b:
        finding["userTokenForwarded"] = bool(user_token)
        try:
            tok, client_id = service_principal_token()
            return Auth(MODE_B, tok, None, client_id, "Mode B forced by the user (Force Mode B switch)"), finding
        except Exception as e:
            finding["modeBError"] = f"{type(e).__name__}: {e}"[:500]
            return None, finding
    if user_token:
        finding["userTokenForwarded"] = True
        h = probe("/health", user_token)
        finding["modeAHealth"] = {k: h.get(k) for k in ("httpStatus", "ms", "error", "redirectHost")}
        if h.get("httpStatus") == 200:
            return Auth(MODE_A, user_token, email, None, "user token accepted by server /health"), finding
        finding["modeARejected"] = True
    try:
        tok, client_id = service_principal_token()
        note = "no user token forwarded" if not user_token else (
            f"user token rejected by server (HTTP {finding['modeAHealth'].get('httpStatus')}); fell back to service principal")
        return Auth(MODE_B, tok, None, client_id, note), finding
    except Exception as e:
        finding["modeBError"] = f"{type(e).__name__}: {e}"[:500]
        return None, finding


def reuse_auth(headers: Any, decision: dict) -> Auth | None:
    """Rebuild Auth from an earlier token-free decision without probing the server again
    (code review L2). decision = {"mode", "note"}. Returns None if it can no longer be used."""
    mode = (decision or {}).get("mode")
    note = (decision or {}).get("note") or ""
    if mode == MODE_A:
        tok = header(headers, "x-forwarded-access-token")
        return Auth(MODE_A, tok, header(headers, "x-forwarded-email"), None, note) if tok else None
    if mode == MODE_B:
        try:
            tok, client_id = service_principal_token()
        except Exception:  # noqa: BLE001 - caller re-resolves from scratch
            return None
        return Auth(MODE_B, tok, None, client_id, note)
    return None


# ---------------------------------------------------------------- MCP

def _recordable(e: BaseException) -> bool:
    """Errors a call records instead of raising (code review L4): ordinary exceptions and
    asyncio cancellation, including anyio exception groups made only of those.
    KeyboardInterrupt, SystemExit and GeneratorExit always propagate."""
    if isinstance(e, BaseExceptionGroup):
        return all(_recordable(s) for s in e.exceptions)
    return isinstance(e, (Exception, asyncio.CancelledError))


def _flatten(e: BaseException) -> str:
    """Readable message for anyio ExceptionGroups."""
    subs = getattr(e, "exceptions", None)
    if subs:
        return "; ".join(_flatten(s) for s in subs)
    return f"{type(e).__name__}: {e}"[:800]


async def _with_session(token: str, fn, statuses: list, timing: dict | None = None):
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def on_response(resp):
        statuses.append(int(resp.status_code))

    extra = {"transport": _TRANSPORT} if _TRANSPORT is not None else {}
    client = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx2.Timeout(HTTP_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
        event_hooks={"response": [on_response]},
        **extra,
    )
    async with client:
        # Stateless server: GET/DELETE /mcp return 405, so never send the DELETE.
        async with streamable_http_client(MCP_URL, http_client=client, terminate_on_close=False) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write, read_timeout_seconds=HTTP_TIMEOUT_S) as session:
                init = await session.initialize()
                t0 = time.monotonic()
                res = await fn(session)
                if timing is not None:  # code review L9: the request alone, without session setup
                    timing["callMs"] = int((time.monotonic() - t0) * 1000)
                return init, res


def list_tools(token: str) -> dict:
    """initialize + tools/list in a fresh session."""
    statuses: list = []
    t0 = time.monotonic()
    out: dict = {"tools": None, "serverInfo": None, "error": None}

    async def go(session):
        return await session.list_tools()

    try:
        init, res = asyncio.run(_with_session(token, go, statuses))
        si = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
        out["serverInfo"] = {"name": getattr(si, "name", None), "version": getattr(si, "version", None)}
        out["tools"] = [
            {"name": t.name, "inputs": sorted(((_schema(t) or {}).get("properties") or {}).keys())}
            for t in res.tools
        ]
    except BaseException as e:  # noqa: BLE001 - filtered by _recordable
        if not _recordable(e):
            raise
        out["error"] = _flatten(e)
    out["httpStatuses"] = statuses
    out["httpStatus"] = statuses[-1] if statuses else None
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def _schema(tool) -> dict | None:
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)


def call_generate_diagram(token: str, arguments: dict) -> dict:
    """tools/call generate_diagram in a fresh session. Token-free result:
    {isError, meta (server JSON), pngBase64, texts, httpStatus, ms, error}."""
    return call_tool(token, TOOL_NAME, arguments)


def call_generate_choropleth(token: str, arguments: dict) -> dict:
    """tools/call generate_choropleth in a fresh session. Same result shape, plus
    resources (the text/html widget) and structuredContent."""
    return call_tool(token, CHOROPLETH_TOOL_NAME, arguments)


def call_tool(token: str, name: str, arguments: dict) -> dict:
    statuses: list = []
    timing: dict = {}
    t0 = time.monotonic()
    out: dict = {"isError": None, "meta": None, "pngBase64": None, "imageMime": None, "resources": [],
                 "structuredContent": None, "error": None}

    async def go(session):
        return await session.call_tool(name, arguments, read_timeout_seconds=HTTP_TIMEOUT_S)

    try:
        _init, res = asyncio.run(_with_session(token, go, statuses, timing))
        out.update(parse_call_result(res))
    except BaseException as e:  # noqa: BLE001 - filtered by _recordable
        if not _recordable(e):
            raise
        out["error"] = _flatten(e)
    out["callMs"] = timing.get("callMs")
    out["httpStatuses"] = statuses
    out["httpStatus"] = statuses[-1] if statuses else None
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def parse_call_result(res) -> dict:
    """Pure: CallToolResult -> {isError, meta, pngBase64, imageMime, resources, structuredContent,
    metaParseError}. meta is the first text item that is a JSON object (generate_choropleth puts a
    plain-language summary first); metaParseError is set only if no text item is."""
    is_error = getattr(res, "is_error", None)
    if is_error is None:
        is_error = getattr(res, "isError", False)
    structured = getattr(res, "structured_content", None)
    if structured is None:
        structured = getattr(res, "structuredContent", None)
    out = {"isError": bool(is_error), "meta": None, "pngBase64": None, "imageMime": None, "resources": [],
           "structuredContent": structured if isinstance(structured, dict) else None, "metaParseError": None,
           "texts": []}  # text items that are not JSON (generate_choropleth's plain-language summary)
    parse_error = None
    for item in getattr(res, "content", None) or []:
        kind = getattr(item, "type", None)
        if kind == "image" and out["pngBase64"] is None:
            out["pngBase64"] = getattr(item, "data", None)
            out["imageMime"] = getattr(item, "mime_type", None) or getattr(item, "mimeType", None)
        elif kind == "resource":
            r = getattr(item, "resource", None)
            out["resources"].append({
                "uri": str(getattr(r, "uri", "") or ""),
                "mimeType": getattr(r, "mime_type", None) or getattr(r, "mimeType", None),
                "text": getattr(r, "text", None),
            })
        elif kind == "text" and out["meta"] is None:
            text = getattr(item, "text", "") or ""
            try:
                parsed = json.loads(text)
            except ValueError as e:
                parse_error = parse_error or f"text content is not JSON: {e}"[:300]
                out["texts"].append(text)
                continue
            if isinstance(parsed, dict):
                out["meta"] = parsed
            else:
                parse_error = parse_error or "text content is JSON but not an object"
    if out["meta"] is None and parse_error:
        out["metaParseError"] = parse_error
    return out
