"""Step 3 of the analyst review: ask Lancelot for a county choropleth.

Only public identifiers leave this app: disaster number, and optionally the
project worksheet (PW) number, applicant ID and sigma threshold to match the
check that ran. Lancelot downloads the public OpenFEMA records itself.
Lancelot is BETA and keeps inputs in its trace logs for 30 days.
"""

from __future__ import annotations

import re
import time
from typing import Any

from fema_oversight import lancelot_client as lancelot

_APPLICANT = re.compile(r"^[A-Za-z0-9-]{1,32}$")
_DETECTORS = ("detect_category_outliers", "get_cost_share_anomalies")


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean_request(raw: Any) -> dict[str, Any] | None:
    """Validate a map request. Returns None unless disaster_number is valid."""
    if not isinstance(raw, dict):
        return None
    disaster = _int(raw.get("disaster_number"))
    if disaster is None or not 1 <= disaster <= 99999:
        return None
    out: dict[str, Any] = {"disaster_number": disaster}
    pw = _int(raw.get("pw_number"))
    if pw is not None and 1 <= pw <= 10_000_000:
        out["pw_number"] = pw
        applicant = raw.get("applicant_id")
        if isinstance(applicant, str) and _APPLICANT.match(applicant):
            out["applicant_id"] = applicant
    sigma = raw.get("sigma_threshold")
    if isinstance(sigma, (int, float)) and not isinstance(sigma, bool) and 1 <= sigma <= 10:
        out["sigma_threshold"] = float(sigma)
    return out


def map_target(tool_calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick what to map from a finished review, or None if no disaster.

    Priority: the evidence-brief project, then the top flagged project of a
    cost check, then any disaster number the AI used.
    """
    ok = [
        c
        for c in tool_calls
        if isinstance(c.get("result"), dict) and not c["result"].get("error")
    ]

    def sigma_of(call: dict[str, Any]) -> Any:
        if call.get("tool") == "detect_category_outliers":
            return (call.get("arguments") or {}).get("sigma_threshold")
        return None

    sigma = next((sigma_of(c) for c in ok if sigma_of(c) is not None), None)

    for call in ok:
        if call.get("tool") != "generate_evidence_brief":
            continue
        result, args = call["result"], call.get("arguments") or {}
        records = result.get("source_records") or []
        first = records[0] if records and isinstance(records[0], dict) else {}
        req = clean_request(
            {
                "disaster_number": first.get("disaster_number") or args.get("disaster_number"),
                "pw_number": first.get("pw_number") or result.get("pw_number"),
                "applicant_id": first.get("applicant_id") or args.get("applicant_id"),
                "sigma_threshold": sigma,
            }
        )
        if req:
            return req

    for call in ok:
        if call.get("tool") not in _DETECTORS:
            continue
        items = call["result"].get("items") or []
        if items and isinstance(items[0], dict):
            top = items[0]
            req = clean_request(
                {
                    "disaster_number": top.get("disaster_number"),
                    "pw_number": top.get("pw_number"),
                    "applicant_id": top.get("applicant_id"),
                    "sigma_threshold": sigma,
                }
            )
            if req:
                return req

    for call in ok:
        req = clean_request(
            {
                "disaster_number": (call.get("arguments") or {}).get("disaster_number"),
                "sigma_threshold": sigma,
            }
        )
        if req:
            return req
    return None


async def _choropleth(req: dict[str, Any]) -> dict[str, Any]:
    return await lancelot.generate_choropleth(
        req["disaster_number"],
        pw_number=req.get("pw_number"),
        applicant_id=req.get("applicant_id"),
        sigma_threshold=req.get("sigma_threshold"),
    )


async def run_map(req: dict[str, Any]) -> dict[str, Any]:
    """Call Lancelot. If the highlighted PW is rejected, retry once without it."""
    started = time.perf_counter()
    attempts = [dict(req)]
    result = await _choropleth(req)
    fallback = False
    if result.get("isError") and "pw_number" in req:
        base = {k: v for k, v in req.items() if k not in ("pw_number", "applicant_id")}
        attempts.append(base)
        result = await _choropleth(base)
        fallback = True
    return {
        "request": attempts[-1],
        "attempts": attempts,
        "fallback_without_highlight": fallback,
        "lancelot": result,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
