"""Lancelot Beta test page: tools/list, generate_diagram, generate_choropleth.

Every call to Lancelot runs as this app's service principal (see
lancelot_client). The test endpoints take no user input: they only send the
fixed synthetic workflow below and public disaster 4856, because Lancelot is
BETA and keeps inputs in its trace logs for 30 days.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from starlette.responses import HTMLResponse, JSONResponse

from fema_oversight import lancelot_client as lancelot

TEST_DISASTER = 4856
SYNTHETIC_WORKFLOW = {
    "name": "Synthetic project review workflow (test data)",
    "steps": [
        {"id": "intake", "label": "Receive project worksheet", "next": ["screen"]},
        {"id": "screen", "label": "Run cost outlier check", "next": ["flagged", "clear"]},
        {"id": "flagged", "label": "Analyst reviews evidence", "next": ["close"]},
        {"id": "clear", "label": "No indicator raised", "next": ["close"]},
        {"id": "close", "label": "Record decision", "next": []},
    ],
}
LANCELOT_SLOTS = asyncio.Semaphore(2)
NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _same_origin(request) -> bool:
    origin = request.headers.get("origin", "")
    host = request.headers.get("x-forwarded-host", request.headers.get("host"))
    return bool(origin) and urlsplit(origin).netloc == host


async def _run(request, call):
    if not _same_origin(request):
        return JSONResponse({"error": "Same-origin request required."}, status_code=403)
    try:
        async with LANCELOT_SLOTS:
            result = await asyncio.wait_for(call(), timeout=170)
        return JSONResponse(result, headers=NO_STORE)
    except lancelot.LancelotAccessError as exc:
        return JSONResponse({"error": str(exc), "accessDenied": True}, status_code=403)
    except lancelot.LancelotError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Lancelot did not answer in time."}, status_code=504)


def register_lancelot_web(server) -> None:
    @server.custom_route("/lancelot", methods=["GET"])
    async def lancelot_page(request):
        return HTMLResponse(
            Path(__file__).with_name("lancelot.html").read_text(encoding="utf-8"),
            headers=NO_STORE,
        )

    @server.custom_route("/lancelot/test/tools", methods=["POST"])
    async def lancelot_tools(request):
        async def call():
            return {"tools": await lancelot.list_tools()}

        return await _run(request, call)

    @server.custom_route("/lancelot/test/diagram", methods=["POST"])
    async def lancelot_diagram(request):
        async def call():
            return await lancelot.generate_diagram(
                data=json.dumps(SYNTHETIC_WORKFLOW),
                hint="Flowchart of a synthetic review workflow (test data).",
            )

        return await _run(request, call)

    @server.custom_route("/lancelot/test/choropleth", methods=["POST"])
    async def lancelot_choropleth(request):
        async def call():
            return await lancelot.generate_choropleth(TEST_DISASTER)

        return await _run(request, call)
