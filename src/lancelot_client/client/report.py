"""result.json and the self-contained report.html (brief section 5).

report.html rules: inline CSS only, PNGs as data URIs, no JavaScript, no
links, every piece of text HTML-escaped.
"""

from __future__ import annotations

import base64
import html
import json

from client.suite import TIMING_NOTES, tally

RESULT_SCHEMA = "lancelot-client/result/v1"


def build_result(*, client_run_id: str, kind: str, started_at: str, finished_at: str, auth: dict,
                 auth_finding: dict, cases: list, versions: dict, storage_errors: list,
                 run_dir: str, server_base: str) -> dict:
    return {
        "schema": RESULT_SCHEMA,
        "clientRunId": client_run_id,
        "kind": kind,  # "suite" | "try-it"
        "startedAt": started_at,
        "finishedAt": finished_at,
        "server": server_base,
        "auth": auth,  # token-free
        "authFinding": auth_finding,
        "versions": versions,
        "timingNotes": TIMING_NOTES,
        "summary": tally(cases),
        "cases": cases,
        "storage": {"runDir": run_dir, "errors": storage_errors},
    }


def summary_of(result: dict) -> dict:
    """Small summary for client-runs/latest/summary.json."""
    return {
        "schema": "lancelot-client/summary/v1",
        "clientRunId": result["clientRunId"],
        "kind": result["kind"],
        "startedAt": result["startedAt"],
        "finishedAt": result["finishedAt"],
        "authMode": result["auth"].get("mode"),
        "summary": result["summary"],
        "runDir": result["storage"]["runDir"],
        "cases": [{"id": c["id"], "verdict": c["verdict"], "serverRunId": c.get("serverRunId")} for c in result["cases"]],
    }


def e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


_CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:24px;color:#1b1b1b;background:#fff}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:24px 0 8px}
.meta{color:#555;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #d0d0d0;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f2f2f2}
.v{font-weight:700;padding:2px 8px;border-radius:4px;display:inline-block}
.PASS{background:#d6f5dd;color:#11632a}.FAIL{background:#fbd5d5;color:#8a1111}
.INFO{background:#dde8fb;color:#123a7a}.SKIP{background:#eee;color:#444}
.mode{font-weight:700}
pre{white-space:pre-wrap;word-break:break-word;background:#f7f7f7;padding:8px;font-size:12px;margin:4px 0}
details{margin:8px 0;border:1px solid #ddd;border-radius:4px;padding:6px 10px}
summary{cursor:pointer;font-weight:600}
img{max-width:100%;border:1px solid #ccc;margin-top:6px}
.warn{background:#fff4d6;border:1px solid #e6c35c;padding:8px;border-radius:4px}
"""


def render_html(result: dict, pngs: dict, widgets: dict | None = None) -> str:
    """widgets: case id -> map widget HTML. This page blocks scripts and has no links, so the
    interactive maps are named as separate files in the run folder rather than embedded."""
    widgets = widgets or {}
    s = result["summary"]
    auth = result.get("auth") or {}
    out = ["<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">",
           "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'\">",
           f"<title>{e(result['clientRunId'])}</title><style>{_CSS}</style></head><body>"]
    out.append(f"<h1>lancelot-client {e(result['kind'])} report</h1>")
    out.append(f"<div class=\"meta\">clientRunId {e(result['clientRunId'])} | {e(result['startedAt'])} to "
               f"{e(result['finishedAt'])} | server {e(result['server'])}</div>")
    out.append(f"<p>Auth mode: <span class=\"mode\">{e(auth.get('mode'))}</span> {e(auth.get('note'))}</p>")
    out.append("<p>" + " ".join(f"<span class=\"v {k}\">{e(k)} {e(v)}</span>" for k, v in s.items()) + "</p>")
    if (result.get("storage") or {}).get("errors"):
        out.append("<div class=\"warn\">Storage errors (results above are unaffected):<pre>"
                   + e(json.dumps(result["storage"]["errors"], indent=2)) + "</pre></div>")

    out.append("<h2>Cases</h2><table><tr><th>Id</th><th>Case</th><th>Verdict</th><th>Expected</th>"
               "<th>Actual</th><th>ms</th><th>server runId</th><th>trace</th></tr>")
    for c in result["cases"]:
        st = c.get("serverTrace") or {}
        trace = "" if not st else (f"{'found' if st.get('found') else 'missing'}; outcome {st.get('outcome')}"
                                   f"{'' if st.get('match') else ' (mismatch)'}")
        out.append(f"<tr><td>{e(c['id'])}</td><td>{e(c['title'])}</td>"
                   f"<td><span class=\"v {e(c['verdict'])}\">{e(c['verdict'])}</span></td>"
                   f"<td>{e(c.get('expected'))}</td><td>{e(c.get('actual'))}</td><td>{e(c.get('clientMs'))}</td>"
                   f"<td>{e(c.get('serverRunId'))}</td><td>{e(trace)}</td></tr>")
    out.append("</table>")

    out.append("<h2>Details</h2>")
    for c in result["cases"]:
        out.append(f"<details><summary>{e(c['id'])} {e(c['title'])} - {e(c['verdict'])}</summary>")
        if c.get("note"):
            out.append(f"<p>{e(c['note'])}</p>")
        out.append("<pre>" + e(json.dumps(c, indent=2, default=str)) + "</pre>")
        w = c.get("widget") or {}
        if c["id"] in widgets and w.get("file"):
            run_dir = (result.get("storage") or {}).get("runDir") or ""
            out.append(f"<p>Interactive map: file <code>{e(run_dir)}/{e(w['file'])}</code> "
                       f"({e(w.get('bytes'))} bytes, sha256 {e(w.get('sha256'))}). It is also shown, with a "
                       f"feedback form, on the client's Test suite page.</p>")
        png = pngs.get(c["id"])
        if png:
            out.append(f"<img alt=\"{e(c['id'])} diagram\" src=\"data:image/png;base64,"
                       f"{base64.b64encode(png).decode('ascii')}\">")
        out.append("</details>")

    out.append("<h2>Auth finding</h2><pre>" + e(json.dumps(result.get("authFinding"), indent=2)) + "</pre>")
    out.append("<h2>Versions</h2><pre>" + e(json.dumps(result.get("versions"), indent=2)) + "</pre>")
    out.append("<h2>Timings</h2><pre>" + e(json.dumps(result.get("timingNotes"), indent=2)) + "</pre>")
    out.append("</body></html>")
    return "".join(out)
