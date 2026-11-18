"""Same-origin analyst UI behind the existing Databricks Apps authentication."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

from starlette.responses import HTMLResponse, JSONResponse, Response

from fema_oversight import lancelot_client as lancelot
from fema_oversight.analyst import run_review
from fema_oversight.review_map import clean_request, run_map

REVIEW_SLOTS = asyncio.Semaphore(2)
MAP_SLOTS = asyncio.Semaphore(2)
NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

# Faded backgrounds of the three question cards. Fixed allowlist: no user
# input reaches the file system. Files are 500x500 JPEGs (64-92 KB).
STATIC = Path(__file__).with_name("static")
CARD_IMAGES = ("q1-bridge-repair.jpg", "q2-power-repair.jpg", "q3-duplicate.jpg")
IMAGE_HEADERS = {"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}


def register_web(server):
    @server.custom_route("/", methods=["GET"])
    async def home(request):
        return HTMLResponse(
            Path(__file__).with_name("analyst.html").read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def card_image(request):
        name = request.url.path.rsplit("/", 1)[-1]
        try:
            data = (STATIC / name).read_bytes() if name in CARD_IMAGES else None
        except OSError:
            data = None
        if data is None:
            return Response(status_code=404)
        return Response(data, media_type="image/jpeg", headers=IMAGE_HEADERS)

    for name in CARD_IMAGES:
        server.custom_route(f"/static/{name}", methods=["GET"])(card_image)

    @server.custom_route("/review", methods=["POST"])
    async def review(request):
        origin = request.headers.get("origin", "")
        host = request.headers.get("x-forwarded-host", request.headers.get("host"))
        if not origin or urlsplit(origin).netloc != host:
            return JSONResponse(
                {"error": "Same-origin request required."}, status_code=403
            )
        body = await request.body()
        if len(body) > 12000:
            return JSONResponse({"error": "Question is too long."}, status_code=413)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                return JSONResponse({"error": "Invalid request."}, status_code=400)
            question = payload.get("question", "")
            if not isinstance(question, str) or not 5 <= len(question.strip()) <= 2000:
                return JSONResponse(
                    {"error": "Enter a question of 5-2000 characters."}, status_code=400
                )
            async with REVIEW_SLOTS:
                result = await asyncio.wait_for(
                    run_review(server, question.strip()), timeout=240
                )
            return JSONResponse(result)
        except (ValueError, TypeError):
            return JSONResponse({"error": "Invalid request."}, status_code=400)
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, RuntimeError)
                else "Review failed. Inspect the app logs."
            )
            return JSONResponse({"error": message}, status_code=502)

    @server.custom_route("/review/map", methods=["POST"])
    async def review_map(request):
        """Step 3: send public disaster identifiers to Lancelot for a county map."""
        origin = request.headers.get("origin", "")
        host = request.headers.get("x-forwarded-host", request.headers.get("host"))
        if not origin or urlsplit(origin).netloc != host:
            return JSONResponse(
                {"error": "Same-origin request required."}, status_code=403
            )
        body = await request.body()
        if len(body) > 2000:
            return JSONResponse({"error": "Map request is too long."}, status_code=413)
        try:
            req = clean_request(await request.json())
        except (ValueError, TypeError):
            req = None
        if not req:
            return JSONResponse(
                {"error": "A valid disaster_number is required."}, status_code=400
            )
        try:
            async with MAP_SLOTS:
                result = await asyncio.wait_for(run_map(req), timeout=170)
            return JSONResponse(result, headers=NO_STORE)
        except lancelot.LancelotAccessError as exc:
            return JSONResponse(
                {"error": str(exc), "accessDenied": True}, status_code=403
            )
        except lancelot.LancelotError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        except asyncio.TimeoutError:
            return JSONResponse(
                {"error": "Lancelot did not answer in time."}, status_code=504
            )
