"""The fixed verification suite (brief section 7) and its pure evaluators.

Network access is injected through SuiteDeps so the evaluators and the run
loop can be unit-tested without a server. Cases run sequentially, because the
server renders one diagram at a time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import time
from dataclasses import dataclass, field
from typing import Callable

from client import config
from client.storage import iso, utc_now

EXPECTED_TOOL = "generate_diagram"
EXPECTED_INPUTS = sorted(["data", "fileBase64", "fileName", "workspacePath", "diagramType", "hint"])
# Server D42: a second tool. /health and tools/list must list exactly these, in this order.
CHOROPLETH_TOOL = "generate_choropleth"
# Server D46 added six choropleth map display options; D50 added map_aspect_ratio.
CHOROPLETH_DISPLAY_INPUTS = ["initial_view", "show_pause_button", "show_pw_card", "show_all_categories_card",
                             "legend_position", "click_details", "map_aspect_ratio"]
CHOROPLETH_INPUTS = sorted(["disaster_number", "pw_number", "applicant_id", "sigma_threshold", "as_of"]
                           + CHOROPLETH_DISPLAY_INPUTS)
EXPECTED_TOOLS = [EXPECTED_TOOL, CHOROPLETH_TOOL]
EXPECTED_TOOL_INPUTS = {EXPECTED_TOOL: EXPECTED_INPUTS, CHOROPLETH_TOOL: CHOROPLETH_INPUTS}
CHOROPLETH_ERROR_CODES = {"INVALID_INPUT", "DATA_UNAVAILABLE", "SNAPSHOT_NOT_FOUND", "DISASTER_NOT_LOADED",
                          "PW_NOT_FOUND", "INTERNAL_ERROR"}
WIDGET_MIME = "text/html"
SVG_NS = "http://www.w3.org/2000/svg"
ERROR_CODES = {"INVALID_INPUT", "UNSUPPORTED_FILE", "ACCESS_DENIED", "EXTRACTION_FAILED",
               "LLM_TIMEOUT", "LLM_ERROR", "RENDER_FAILED", "INTERNAL_ERROR"}
CALL_BUDGET_MS = 75_000
OWNER_EMAIL = config.OWNER_EMAIL
OWNER_V11_PATH = config.OWNER_V11_PATH
V12_OTHER_USER_PATH = config.V12_OTHER_USER_PATH
# Code review L6: server error messages are stored verbatim only for error codes whose messages
# describe the request (arguments, file type, paths, permissions), never document content. For
# every other code only the message length and SHA-256 are kept.
MESSAGE_TEXT_CODES = frozenset({"INVALID_INPUT", "UNSUPPORTED_FILE", "ACCESS_DENIED"})
MESSAGE_MAX_CHARS = 300
# Code review L9: what each timing covers.
TIMING_NOTES = {
    "clientMs": "whole client-side case: new MCP session (initialize) + the request, or the HTTP GET",
    "callMs": "the tools/call request alone, after initialize (tools/call cases only)",
}

PASS, FAIL, INFO, SKIP = "PASS", "FAIL", "INFO", "SKIP"

CASES = [
    ("C1", "GET /health"),
    ("C3", "GET /mcp returns 405"),
    ("V4", "MCP initialize + tools/list"),
    ("V5", "data: synthetic JSON workflow"),
    ("V6", "fileBase64: sample.pdf"),
    ("V7a", "fileBase64: sample.docx"),
    ("V7b", "fileBase64: sample.xlsx"),
    ("V8", "data + diagramType 'Sequence diagram'"),
    ("V9", "data + diagramType 'Mindmap' (unsupported)"),
    ("V10a", "no input {}"),
    ("V10b", "data + workspacePath together"),
    ("V12", "workspacePath: another user's folder"),
    ("V14", "data: ~60,000 characters synthetic text"),
    ("M1", "choropleth: DR-4856 with PW 2"),
    ("M2", "choropleth: DR-4673, no PW"),
    ("M3", "choropleth: disaster not loaded"),
    ("M4", "choropleth: as_of with no snapshot"),
    ("M5", "choropleth: sigma_threshold out of range"),
    ("M6", "choropleth: PW not in the disaster"),
    ("T1", "server trace.json exists and matches, per V and M case"),
]


# ------------------------------------------------------------------ helpers

def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def input_desc(kind: str, name: str | None, data: bytes) -> dict:
    """What was sent, without the content itself."""
    return {"kind": kind, "fileName": name, "bytes": len(data), "sha256": sha256(data)}


def png_info(png: bytes | None) -> dict | None:
    """Width/height from the PNG IHDR chunk; None if not a PNG."""
    if not png or len(png) < 24 or png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", png[16:24])
    return {"width": w, "height": h, "bytes": len(png)}


def decode_png(b64: str | None) -> bytes | None:
    if not b64:
        return None
    try:
        return base64.b64decode(b64, validate=False)
    except Exception:  # noqa: BLE001
        return None


def synthetic_long_text(target_chars: int = 60_000) -> str:
    """Deterministic synthetic process text (V14). No real data."""
    parts, i = [], 0
    while sum(len(p) for p in parts) < target_chars:
        i += 1
        parts.append(
            f"Step {i}: The fictional Pallet Town Pokemon Center receives request #{i:05d}. "
            f"Nurse Joy checks the trainer card, assigns healing bay {i % 7 + 1}, and logs the status. "
            f"If the request needs a specialist, it is routed to Professor Oak's lab for review; "
            f"otherwise it is completed and the trainer is notified.\n"
        )
    return "".join(parts)[:target_chars]


def message_record(code: str | None, message) -> tuple[str | None, dict | None]:
    """(stored text or None, messageInfo) for a server error message (code review L6)."""
    if message is None:
        return None, None
    text = str(message)
    keep = code in MESSAGE_TEXT_CODES
    info = {"chars": len(text), "sha256": sha256(text.encode("utf-8")), "stored": keep}
    return (text[:MESSAGE_MAX_CHARS] if keep else None), info


def expected_trace_outcome(rec: dict) -> str | None:
    if rec.get("mcpIsError") is False and rec.get("status") == "OK":
        return "OK"
    if rec.get("mcpIsError") is True:
        return rec.get("errorCode")
    return None


# --------------------------------------------------------------- evaluators
# Each returns (verdict, actual_summary).

def ev_health(r: dict):
    j = r.get("json") or {}
    ok = r.get("httpStatus") == 200 and j.get("phase") == 2 and j.get("tools") == EXPECTED_TOOLS
    return (PASS if ok else FAIL), f"HTTP {r.get('httpStatus')}, phase={j.get('phase')!r}, tools={j.get('tools')!r}" + _err(r)


def ev_get_mcp(r: dict):
    return (PASS if r.get("httpStatus") == 405 else FAIL), f"HTTP {r.get('httpStatus')}" + _err(r)


def ev_tools(r: dict):
    tools = r.get("tools")
    if tools is None:
        return FAIL, f"no tools list ({r.get('error')})"
    by_name = {t.get("name"): t.get("inputs") for t in tools}
    ok = (len(tools) == len(EXPECTED_TOOLS) and set(by_name) == set(EXPECTED_TOOLS)
          and all(by_name[n] == EXPECTED_TOOL_INPUTS[n] for n in EXPECTED_TOOLS))
    return (PASS if ok else FAIL), f"tools={json.dumps(tools)}"


def widget_html(resources: list | None) -> str | None:
    """The first text/html resource (the generate_choropleth widget), or None."""
    for r in resources or []:
        if r.get("mimeType") == WIDGET_MIME and isinstance(r.get("text"), str):
            return r["text"]
    return None


def widget_info(resources: list | None) -> dict | None:
    """Checks on the text/html widget. The record keeps these checks only; the HTML itself is kept
    in SuiteRun.widgets and written next to result.json as <case>.widget.html (D19)."""
    html_items = [r for r in (resources or []) if r.get("mimeType") == WIDGET_MIME and isinstance(r.get("text"), str)]
    if not html_items:
        return None
    r = html_items[0]
    html = r["text"]
    b = html.encode("utf-8")
    urls = [u for u in re.findall(r"https?://[^\s\"'<>)]+", html) if not u.startswith(SVG_NS)]
    return {
        "uri": r.get("uri"), "mimeType": r.get("mimeType"), "bytes": len(b), "sha256": sha256(b),
        "resources": len(resources or []),
        "csp": "Content-Security-Policy" in html and "default-src 'none'" in html,
        "externalUrls": sorted(set(urls))[:5],
        "hasScript": "<script" in html,  # the page script builds the map
    }


def _choropleth_summary(rec: dict) -> str:
    s = _call_summary(rec)
    c = rec.get("choropleth") or {}
    w = rec.get("widget")
    if c:
        s += (f", DR-{c.get('disasterNumber')} snapshot {c.get('snapshotDate')}, projects={c.get('projects')} "
              f"(mapped {c.get('projectsMapped')}), outliers={c.get('outliers')}, "
              f"highlightPw={c.get('highlightPw')!r}, mapDrawn={c.get('mapDrawn')}")
    if w:
        s += f", widget {w['bytes']} bytes, csp={w['csp']}, externalUrls={len(w['externalUrls'])}"
    im = rec.get("image")
    if im:
        s += (f", image error {im['error']}" if im.get("error") else
              f", image {im.get('width')}x{im.get('height')} sha={im.get('shaMatches')} mapDrawn={im.get('mapDrawn')}"
              f" affected={im.get('affectedDrawn')}")
    return s


def ev_choropleth_ok(rec: dict, disaster: int, pw: int | None = None):
    """OK result with a self-contained widget for the right disaster. Counts are not fixed:
    the data is reloaded daily."""
    c = rec.get("choropleth") or {}
    w = rec.get("widget") or {}
    ok = (not rec.get("transportError") and rec.get("mcpIsError") is False and rec.get("status") == "OK"
          and c.get("disasterNumber") == disaster and isinstance(c.get("outliers"), int)
          and c.get("mapDrawn") is True and bool(w) and w.get("csp") is True and not w.get("externalUrls")
          and str(w.get("uri") or "").startswith("ui://"))
    im = rec.get("image") or {}
    # D44: always a 1000x1000 PNG matching structuredContent.image (map or logo-only fallback).
    ok = ok and im.get("width") == 1000 and im.get("height") == 1000 and im.get("shaMatches") is True
    if ok and pw is not None:
        ok = c.get("highlightPw") == pw
    return (PASS if ok else FAIL), _choropleth_summary(rec)


def ev_choropleth_error(rec: dict, code: str):
    ok = (not rec.get("transportError") and rec.get("mcpIsError") is True and rec.get("errorCode") == code
          and not rec.get("widget") and not rec.get("image") and not rec.get("png"))
    return (PASS if ok else FAIL), _choropleth_summary(rec)


def _err(r: dict) -> str:
    return f", error={r['error']}" if r.get("error") else ""


def _call_summary(rec: dict) -> str:
    if rec.get("transportError"):
        return f"transport error after {rec.get('clientMs')} ms: {rec['transportError']}"
    s = f"isError={rec.get('mcpIsError')}, status={rec.get('status')}"
    if rec.get("errorCode"):
        s += f", errorCode={rec['errorCode']}, stage={rec.get('stage')}"
    if rec.get("diagramType"):
        s += f", diagramType={rec['diagramType']!r}"
    if rec.get("png"):
        s += f", png {rec['png']['width']}x{rec['png']['height']}"
    s += f", {rec.get('clientMs')} ms"
    return s


def ev_ok(rec: dict, max_ms: int | None = None, want_type: str | None = None,
          select_zero: bool = False, not_type: str | None = None):
    ok = (not rec.get("transportError") and rec.get("mcpIsError") is False
          and rec.get("status") == "OK" and rec.get("png") is not None)
    if ok and max_ms is not None and (rec.get("clientMs") or 0) >= max_ms:
        ok = False
    if ok and want_type is not None and rec.get("diagramType") != want_type:
        ok = False
    if ok and select_zero and (rec.get("timingsMs") or {}).get("select") != 0:
        ok = False
    if ok and not_type is not None and rec.get("diagramType") == not_type:
        ok = False
    actual = _call_summary(rec)
    if select_zero:
        actual += f", timingsMs.select={(rec.get('timingsMs') or {}).get('select')!r}"
    return (PASS if ok else FAIL), actual


def ev_error(rec: dict, code: str):
    ok = not rec.get("transportError") and rec.get("mcpIsError") is True and rec.get("errorCode") == code
    return (PASS if ok else FAIL), _call_summary(rec)


def ev_v14(rec: dict):
    if rec.get("transportError"):
        return FAIL, _call_summary(rec)
    fast = (rec.get("clientMs") or 0) < CALL_BUDGET_MS
    ok_result = rec.get("mcpIsError") is False and rec.get("status") == "OK" and rec.get("png") is not None
    clean_error = rec.get("mcpIsError") is True and rec.get("errorCode") in ERROR_CODES
    return (PASS if fast and (ok_result or clean_error) else FAIL), _call_summary(rec)


def ev_trace(rec: dict, trace: dict | None, err: str | None) -> dict:
    """serverTrace block for one case."""
    from client.storage import server_trace_path

    want = expected_trace_outcome(rec)
    out = {"path": server_trace_path(rec.get("serverRunId") or ""), "found": trace is not None,
           "outcome": None, "expectedOutcome": want, "match": False, "error": err}
    if trace is not None:
        out["outcome"] = (trace.get("run") or {}).get("outcome")
        out["match"] = want is not None and out["outcome"] == want
    return out


# ----------------------------------------------------------------- the run

@dataclass
class SuiteDeps:
    auth: dict  # Auth.public()
    http_get: Callable[[str], dict]
    list_tools: Callable[[], dict]
    call_tool: Callable[[dict], dict]
    read_trace: Callable[[str], tuple]  # server runId -> (trace|None, error|None)
    load_sample: Callable[[str], bytes | None]
    call_choropleth: Callable[[dict], dict] | None = None  # M cases are SKIP without it
    sleep: Callable[[float], None] = time.sleep
    trace_wait_s: tuple = (0, 3, 6, 10)


@dataclass
class SuiteRun:
    cases: list = field(default_factory=list)
    pngs: dict = field(default_factory=dict)  # case id -> PNG bytes
    widgets: dict = field(default_factory=dict)  # case id -> generate_choropleth widget HTML (D19)


def _base(case_id: str, title: str, auth: dict) -> dict:
    return {"id": case_id, "title": title, "authMode": auth.get("mode"), "startedAt": iso(utc_now()),
            "endedAt": None, "clientMs": None, "inputs": [], "arguments": {}, "httpStatus": None,
            "mcpIsError": None, "status": None, "errorCode": None, "stage": None, "message": None,
            "serverRunId": None, "diagramType": None, "png": None, "expected": "", "actual": "",
            "verdict": None, "note": None, "serverTrace": None}


def _finish(rec: dict, verdict: str, actual: str) -> dict:
    rec["verdict"], rec["actual"], rec["endedAt"] = verdict, actual, iso(utc_now())
    return rec


def apply_call(rec: dict, out: dict) -> bytes | None:
    """Copy a call_generate_diagram result into a case record. Returns PNG bytes."""
    meta = out.get("meta") or {}
    png = decode_png(out.get("pngBase64"))
    message, message_info = message_record(meta.get("errorCode"), meta.get("message"))
    rec.update({
        "clientMs": out.get("ms"), "callMs": out.get("callMs"),
        "httpStatus": out.get("httpStatus"), "httpStatuses": out.get("httpStatuses"),
        "mcpIsError": out.get("isError"), "transportError": out.get("error"),
        "status": meta.get("status"), "errorCode": meta.get("errorCode"), "stage": meta.get("stage"),
        "message": message, "messageInfo": message_info,
        "serverRunId": meta.get("runId"), "diagramType": meta.get("diagramType"),
        "timingsMs": meta.get("timingsMs"), "endpointUsed": meta.get("endpointUsed"),
        "repaired": meta.get("repaired"), "truncated": meta.get("truncated"),
        "serverWidth": meta.get("width"), "serverHeight": meta.get("height"),
        "imageMime": out.get("imageMime"), "metaParseError": out.get("metaParseError"),
        "png": png_info(png),
    })
    return png


def image_info(png: bytes | None, structured: dict) -> dict | None:
    """Checks on the square PNG (server D44): the bytes against structuredContent.image."""
    im = structured.get("image") if isinstance(structured, dict) else None
    if not png and not im:
        return None
    size = png_info(png) or {}
    digest = sha256(png) if png else None
    im = im or {}
    return {
        "bytes": len(png) if png else None, "sha256": digest, "width": size.get("width"), "height": size.get("height"),
        "shaMatches": bool(digest) and digest == im.get("sha256"), "mapDrawn": im.get("mapDrawn"), "reason": im.get("reason"),
        "title": im.get("title"), "affectedDrawn": im.get("affectedDrawn"), "declarationStatus": (im.get("declaration") or {}).get("status"),
    }


def apply_choropleth(rec: dict, out: dict) -> bytes | None:
    """apply_call plus the choropleth fields. Keeps counts and checks, not project content.
    Returns the square PNG bytes (D44), if any."""
    png = apply_call(rec, out)
    sc = out.get("structuredContent") or {}
    meta = out.get("meta") or {}
    src = sc or meta
    h = src.get("highlight") or {}
    m = src.get("map") or {}
    totals = src.get("totals") or {}
    rec["choropleth"] = None if not src or rec.get("mcpIsError") else {
        "disasterNumber": src.get("disasterNumber"), "states": src.get("states"),
        "snapshotDate": src.get("snapshotDate"), "sigmaThreshold": src.get("sigmaThreshold"),
        # Server analysis.totals field names (lancelot-beta lib/tools/choropleth/lib/analysis.mjs).
        "initialView": src.get("initialView"), "outliers": totals.get("outliers"),
        "projects": totals.get("projectsAll"), "projectsMapped": totals.get("projectsMapped"),
        "unmappable": totals.get("unmappable"), "outlierCounties": totals.get("outlierCounties"),
        "statewideOutliers": totals.get("statewideOutliers"),
        "highlightPw": h.get("pw"), "highlightFlagged": h.get("flagged"),
        "mapDrawn": m.get("drawn"), "countiesNotInShapes": len(m.get("countiesNotInShapes") or []),
        "structuredContent": bool(sc),
    }
    rec["widget"] = widget_info(out.get("resources"))
    rec["image"] = None if rec.get("mcpIsError") else image_info(png, src)
    if rec["image"] is None and src.get("imageError"):
        rec["image"] = {"error": src.get("imageError")}
    return png


def _arg_summary(args: dict) -> dict:
    """Arguments without document content."""
    s = {}
    for k, v in args.items():
        if k in ("data", "fileBase64"):
            s[k] = f"<{len(v)} chars>"
        else:
            s[k] = v
    return s


def run_suite(deps: SuiteDeps, on_case: Callable[[int, dict], None] | None = None,
              on_start: Callable[[int, str, str], None] | None = None, run: SuiteRun | None = None) -> SuiteRun:
    """Runs every case in order. Pass `run` to observe cases/pngs as they accumulate."""
    run = run if run is not None else SuiteRun()
    auth = deps.auth
    total = len(CASES)

    def emit(rec):
        run.cases.append(rec)
        if on_case:
            on_case(len(run.cases), rec)

    def start(case_id, title):
        if on_start:
            on_start(len(run.cases) + 1, case_id, title)
        return _base(case_id, title, auth)

    def http_case(case_id, title, path, expected, evaluator):
        rec = start(case_id, title)
        rec["expected"] = expected
        r = deps.http_get(path)
        rec.update({"clientMs": r.get("ms"), "httpStatus": r.get("httpStatus"), "transportError": r.get("error")})
        if case_id == "C1":
            j = r.get("json") or {}
            rec["health"] = {k: j.get(k) for k in ("status", "phase", "mcpEndpoint", "tools", "selftest")}
        emit(_finish(rec, *evaluator(r)))

    def call_case(case_id, title, args, inputs, expected, evaluator, note=None):
        rec = start(case_id, title)
        rec.update({"expected": expected, "inputs": inputs, "arguments": _arg_summary(args), "note": note})
        out = deps.call_tool(args)
        png = apply_call(rec, out)
        if png:
            run.pngs[case_id] = png
        emit(_finish(rec, *evaluator(rec)))

    def missing(case_id, title, expected, what):
        rec = start(case_id, title)
        rec["expected"] = expected
        emit(_finish(rec, FAIL, f"sample missing: {what} (copy it into samples/)"))

    # C1, C3, V4. C2 (user-token forwarding probe) was removed 2026-11-12 (client D-entry): a client
    # app's user token is not forwarded to another app, by design.
    http_case("C1", "GET /health", "/health", f"200, phase 2, tools == {EXPECTED_TOOLS}", ev_health)
    http_case("C3", "GET /mcp returns 405", "/mcp", "HTTP 405", ev_get_mcp)

    rec = start("V4", "MCP initialize + tools/list")
    rec["expected"] = "exactly two tools: " + "; ".join(
        f"{n} with inputs {', '.join(EXPECTED_TOOL_INPUTS[n])}" for n in EXPECTED_TOOLS)
    lt = deps.list_tools()
    rec.update({"clientMs": lt.get("ms"), "httpStatus": lt.get("httpStatus"), "transportError": lt.get("error"),
                "serverInfo": lt.get("serverInfo"), "tools": lt.get("tools")})
    emit(_finish(rec, *ev_tools(lt)))

    # V5 small synthetic JSON workflow
    wf = deps.load_sample("synthetic_workflow.json")
    if wf is None:
        missing("V5", "data: synthetic JSON workflow", "PNG + OK < 75 s", "synthetic_workflow.json")
    else:
        call_case("V5", "data: synthetic JSON workflow", {"data": wf.decode("utf-8")},
                  [input_desc("data", "synthetic_workflow.json", wf)], "PNG + status OK, client time < 75 s",
                  lambda r: ev_ok(r, max_ms=CALL_BUDGET_MS))

    # V6, V7a, V7b binary samples
    for cid, title, name in (("V6", "fileBase64: sample.pdf", "sample.pdf"),
                             ("V7a", "fileBase64: sample.docx", "sample.docx"),
                             ("V7b", "fileBase64: sample.xlsx", "sample.xlsx")):
        b = deps.load_sample(name)
        if b is None:
            missing(cid, title, "PNG + status OK", name)
            continue
        call_case(cid, title, {"fileBase64": base64.b64encode(b).decode("ascii"), "fileName": name},
                  [input_desc("fileBase64", name, b)], "PNG + status OK", ev_ok)

    # V8, V9 diagramType
    seq = deps.load_sample("synthetic_sequence.txt")
    if seq is None:
        missing("V8", "data + diagramType 'Sequence diagram'", "OK, Sequence diagram", "synthetic_sequence.txt")
    else:
        call_case("V8", "data + diagramType 'Sequence diagram'",
                  {"data": seq.decode("utf-8"), "diagramType": "Sequence diagram"},
                  [input_desc("data", "synthetic_sequence.txt", seq)],
                  "OK, diagramType == 'Sequence diagram', timingsMs.select == 0",
                  lambda r: ev_ok(r, want_type="Sequence diagram", select_zero=True))
    mm = deps.load_sample("synthetic_mindmap.txt")
    if mm is None:
        missing("V9", "data + diagramType 'Mindmap' (unsupported)", "OK, not Mindmap", "synthetic_mindmap.txt")
    else:
        call_case("V9", "data + diagramType 'Mindmap' (unsupported)",
                  {"data": mm.decode("utf-8"), "diagramType": "Mindmap"},
                  [input_desc("data", "synthetic_mindmap.txt", mm)],
                  "OK and diagramType != 'Mindmap' (automatic fallback)",
                  lambda r: ev_ok(r, not_type="Mindmap"))

    # V10a, V10b input validation
    call_case("V10a", "no input {}", {}, [], "isError, INVALID_INPUT", lambda r: ev_error(r, "INVALID_INPUT"))
    small = b'{"steps": ["start", "end"]}'
    call_case("V10b", "data + workspacePath together",
              {"data": small.decode(), "workspacePath": "/Users/nobody@example.invalid/x.txt"},
              [input_desc("data", None, small)], "isError, INVALID_INPUT", lambda r: ev_error(r, "INVALID_INPUT"))

    # V11 (read the caller's own folder through this client) was removed 2026-11-12: it needs the
    # signed-in user's token to reach the server through another app, which must not be possible.
    mode_a = auth.get("mode", "").startswith("A")
    mode_note = None if mode_a else "Mode B: runs as the service principal, not as a human user"

    # V12 another user's folder (must stay ACCESS_DENIED)
    other = V12_OTHER_USER_PATH
    caller = (auth.get("callerEmail") or "").lower()
    if caller != OWNER_EMAIL:
        other = OWNER_V11_PATH
    call_case("V12", "workspacePath: another user's folder", {"workspacePath": other},
              [{"kind": "workspacePath", "workspacePath": other}], "isError, ACCESS_DENIED",
              lambda r: ev_error(r, "ACCESS_DENIED"), note=mode_note)

    # V14 large synthetic text
    big = synthetic_long_text().encode("utf-8")
    call_case("V14", "data: ~60,000 characters synthetic text", {"data": big.decode("utf-8")},
              [input_desc("data", "synthetic_long_text(60000)", big)],
              "OK or a clean coded error, before 75 s; never a dropped connection", ev_v14)

    # M1-M6 generate_choropleth (server D42). Reads the OpenFEMA export; no LLM.
    def map_case(case_id, title, args, expected, evaluator):
        rec = start(case_id, title)
        rec.update({"expected": expected, "arguments": dict(args),
                    "inputs": [{"kind": "arguments", "tool": CHOROPLETH_TOOL}]})
        if deps.call_choropleth is None:
            emit(_finish(rec, SKIP, "client built without a generate_choropleth caller"))
            return
        out = deps.call_choropleth(args)
        png = apply_choropleth(rec, out)
        html = widget_html(out.get("resources"))
        if html is not None:
            run.widgets[case_id] = html
        if png:
            run.pngs[case_id] = png  # written as <case>.png next to result.json
        emit(_finish(rec, *evaluator(rec)))

    map_case("M1", "choropleth: DR-4856 with PW 2", {"disaster_number": 4856, "pw_number": 2},
             "OK, DR-4856, highlight PW 2, map drawn, text/html widget with CSP and no external URLs, "
             "1000x1000 PNG matching structuredContent.image",
             lambda r: ev_choropleth_ok(r, 4856, pw=2))
    map_case("M2", "choropleth: DR-4673, no PW", {"disaster_number": "4673"},
             "OK, DR-4673 (number sent as a string), map drawn, widget with CSP and no external URLs, 1000x1000 PNG",
             lambda r: ev_choropleth_ok(r, 4673))
    map_case("M3", "choropleth: disaster not loaded", {"disaster_number": 1},
             "isError, DISASTER_NOT_LOADED, no widget", lambda r: ev_choropleth_error(r, "DISASTER_NOT_LOADED"))
    map_case("M4", "choropleth: as_of with no snapshot", {"disaster_number": 4856, "as_of": "2020-01-01"},
             "isError, SNAPSHOT_NOT_FOUND, no widget", lambda r: ev_choropleth_error(r, "SNAPSHOT_NOT_FOUND"))
    map_case("M5", "choropleth: sigma_threshold out of range", {"disaster_number": 4856, "sigma_threshold": 0.5},
             "isError, INVALID_INPUT, no widget", lambda r: ev_choropleth_error(r, "INVALID_INPUT"))
    map_case("M6", "choropleth: PW not in the disaster", {"disaster_number": 4856, "pw_number": 999999},
             "isError, PW_NOT_FOUND, no widget", lambda r: ev_choropleth_error(r, "PW_NOT_FOUND"))

    # T1 server traces
    rec = start("T1", "server trace.json exists and matches, per V and M case")
    rec["expected"] = "for every V and M case with a runId: trace.json exists and run.outcome matches"
    t0 = time.monotonic()
    checked = check_traces(run.cases, deps, prefixes=("V", "M"))
    rec["clientMs"] = int((time.monotonic() - t0) * 1000)
    rec["traces"] = checked
    good = [c for c in checked if c["found"] and c["match"]]
    verdict = PASS if checked and len(good) == len(checked) else FAIL
    bad = [f"{c['case']}: found={c['found']} outcome={c['outcome']!r} expected={c['expectedOutcome']!r}"
           + (f" error={c['error']}" if c.get("error") and c["error"] != "NOT_FOUND" else "")
           for c in checked if not (c["found"] and c["match"])]
    actual = f"{len(good)}/{len(checked)} traces found and matching" + ("; " + "; ".join(bad) if bad else "")
    if not checked:
        actual = "no V or M case returned a runId"
    emit(_finish(rec, verdict, actual))
    return run


def check_traces(cases: list, deps, prefixes: tuple = ("V",)) -> list:
    """Read each server trace (it is written after the response), with short retries.
    `deps` needs read_trace, sleep, trace_wait_s."""
    out = []
    for rec in cases:
        if not rec["id"].startswith(prefixes) or not rec.get("serverRunId"):
            continue
        trace, err = None, None
        for wait in deps.trace_wait_s:
            if wait:
                deps.sleep(wait)
            trace, err = deps.read_trace(rec["serverRunId"])
            if trace is not None or err != "NOT_FOUND":
                break
        st = ev_trace(rec, trace, err)
        rec["serverTrace"] = st
        out.append(dict(st, case=rec["id"], serverRunId=rec["serverRunId"]))
    return out


def tally(cases: list) -> dict:
    t = {PASS: 0, FAIL: 0, INFO: 0, SKIP: 0}
    for c in cases:
        t[c.get("verdict") or FAIL] = t.get(c.get("verdict") or FAIL, 0) + 1
    return t
