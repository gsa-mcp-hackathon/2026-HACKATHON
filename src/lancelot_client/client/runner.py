"""Glue: binds auth to the network calls, runs the suite or a try-it call, and
writes everything to client-runs/<date>/<clientRunId>/ (plus latest/ for suites).

Storage is written incrementally (after each case) so a crash mid-run still
leaves a partial result.json. Storage errors are recorded, never raised.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import platform
import time
from pathlib import Path
from types import SimpleNamespace

from client import mcp_client as mc
from client import report, storage, suite

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
OWNER_V11_PATH = suite.OWNER_V11_PATH


REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"


def versions() -> dict:
    v = {"python": platform.python_version()}
    for p in ("mcp", "mcp-types", "httpx2", "httpcore2", "databricks-sdk", "streamlit", "starlette",
              "uvicorn", "requests"):
        try:
            v[p] = md.version(p)
        except md.PackageNotFoundError:
            v[p] = None
    # M4: which lock file this build used, and whether every pin in it is what is installed.
    try:
        lock = REQUIREMENTS.read_bytes()
        v["requirementsSha256"] = hashlib.sha256(lock).hexdigest()
        mismatched = []
        for line in lock.decode("utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "==" not in line:
                continue
            name, want = (x.strip() for x in line.split("==", 1))
            try:
                have = md.version(name)
            except md.PackageNotFoundError:
                have = None
            if have != want:
                mismatched.append(f"{name}: pinned {want}, installed {have}")
        v["pinsMatchInstalled"] = not mismatched
        v["pinMismatches"] = mismatched
    except OSError as e:
        v["requirementsSha256"] = None
        v["pinMismatches"] = [f"cannot read requirements.txt: {e}"]
    return v


def load_sample(name: str) -> bytes | None:
    p = SAMPLES_DIR / name
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def list_samples() -> list[str]:
    try:
        return sorted(p.name for p in SAMPLES_DIR.iterdir() if p.is_file() and not p.name.startswith("."))
    except OSError:
        return []


def make_read_trace(store: storage.Storage):
    def read(run_id: str):
        path = storage.server_trace_path(run_id)
        if not path:
            return None, f"unrecognized runId {run_id!r}"
        return store.read_json(path)
    return read


class RunWriter:
    """Incremental writer for one clientRunId."""

    def __init__(self, kind: str, auth: mc.Auth, finding: dict, store: storage.Storage):
        self.kind, self.auth, self.finding, self.store = kind, auth, finding, store
        self.client_run_id = storage.new_client_run_id()
        self.dir = storage.run_dir(self.client_run_id)
        self.started_at = storage.iso(storage.utc_now())
        self.versions = versions()
        self.written_pngs: set = set()
        self.written_widgets: set = set()

    def result(self, cases: list, finished: bool) -> dict:
        return report.build_result(
            client_run_id=self.client_run_id, kind=self.kind, started_at=self.started_at,
            finished_at=storage.iso(storage.utc_now()) if finished else None, auth=self.auth.public(),
            auth_finding=self.finding, cases=cases, versions=self.versions,
            storage_errors=list(self.store.errors), run_dir=self.dir, server_base=mc.SERVER_BASE)

    def checkpoint(self, cases: list, pngs: dict, widgets: dict | None = None):
        for cid, html in (widgets or {}).items():
            if cid not in self.written_widgets:
                name = f"{storage.safe_name(cid)}.widget.html"
                if self.store.write_bytes(f"{self.dir}/{name}", html.encode("utf-8")):
                    for c in cases:
                        if c["id"] == cid and c.get("widget"):
                            c["widget"]["file"] = name
                self.written_widgets.add(cid)
        for cid, png in pngs.items():
            if cid not in self.written_pngs:
                name = f"{storage.safe_name(cid)}.png"
                if self.store.write_bytes(f"{self.dir}/{name}", png):
                    for c in cases:
                        if c["id"] == cid and c.get("png"):
                            c["png"]["file"] = name
                self.written_pngs.add(cid)
        self.store.write_json(f"{self.dir}/result.json", self.result(cases, finished=False))

    def finish(self, cases: list, pngs: dict, update_latest: bool, widgets: dict | None = None) -> dict:
        self.checkpoint(cases, pngs, widgets)
        res = self.result(cases, finished=True)
        page = report.render_html(res, pngs, widgets)
        self.store.write_bytes(f"{self.dir}/report.html", page.encode("utf-8"))
        if update_latest:
            self.store.write_json(f"{storage.LATEST_DIR}/summary.json", report.summary_of(res))
            self.store.write_bytes(f"{storage.LATEST_DIR}/report.html", page.encode("utf-8"))
        # Final result.json includes any storage errors from the writes above.
        res = self.result(cases, finished=True)
        path = f"{self.dir}/result.json"
        written = self.store.write_json(path, res)
        if not written:
            # Code review L11: result.json cannot record its own failed write. Retry once (now
            # carrying that error); if it still fails, leave a small sidecar naming the errors.
            res = self.result(cases, finished=True)
            written = self.store.write_json(path, res)
            if not written:
                self.store.write_json(f"{self.dir}/result.write-error.json", {
                    "schema": "lancelot-client/write-error/v1", "clientRunId": self.client_run_id,
                    "summary": res["summary"], "errors": list(self.store.errors)})
        res["storage"]["errors"] = list(self.store.errors)
        res["storage"]["resultJsonWritten"] = written
        return res


def run_suite(auth: mc.Auth, finding: dict, store: storage.Storage, on_start=None, on_case=None):
    writer = RunWriter("suite", auth, finding, store)
    deps = suite.SuiteDeps(
        auth=auth.public(),
        http_get=lambda path: mc.http_get(path, auth.token),
        list_tools=lambda: mc.list_tools(auth.token),
        call_tool=lambda args: mc.call_generate_diagram(auth.token, args),
        read_trace=make_read_trace(store),
        load_sample=load_sample,
        call_choropleth=lambda args: mc.call_generate_choropleth(auth.token, args),
    )
    run = suite.SuiteRun()

    def case_done(i, rec):
        writer.checkpoint(run.cases, run.pngs, run.widgets)
        if on_case:
            on_case(i, rec)

    suite.run_suite(deps, on_case=case_done, on_start=on_start, run=run)
    res = writer.finish(run.cases, run.pngs, update_latest=True, widgets=run.widgets)
    return res, run.pngs, run.widgets


FEEDBACK_RATINGS = ("Works as expected", "Works, with problems", "Does not work")
FEEDBACK_MAX_CHARS = 4000


def save_feedback(store: storage.Storage, result: dict, case: dict, rating: str, comment: str,
                  reviewer: str | None) -> str | None:
    """Write reviewer feedback on one map case next to that run's result.json (D19).
    Returns the volume path, or None if the write failed."""
    if rating not in FEEDBACK_RATINGS:
        raise ValueError(f"unknown rating {rating!r}")
    now = storage.utc_now()
    run_id = result["clientRunId"]
    widget = case.get("widget") or {}
    body = {
        "schema": "lancelot-client/feedback/v1", "clientRunId": run_id, "case": case["id"], "title": case.get("title"),
        "verdict": case.get("verdict"), "serverRunId": case.get("serverRunId"), "arguments": case.get("arguments"),
        "widgetSha256": widget.get("sha256"), "widgetFile": widget.get("file"),
        "rating": rating, "comment": (comment or "")[:FEEDBACK_MAX_CHARS], "reviewer": reviewer, "savedAt": storage.iso(now),
    }
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = f"{storage.run_dir(run_id)}/feedback/{storage.safe_name(case['id'])}-{stamp}.json"
    return path if store.write_json(path, body) else None


def try_fema(auth: mc.Auth, finding: dict, store: storage.Storage, args: dict) -> dict:
    """One generate_choropleth call from the Try It - FEMA page (D20). Written like a suite run
    (kind 'try-fema'): result.json, report.html, TRY.widget.html. Returns a token-free dict the
    page keeps in session state."""
    writer = RunWriter("try-fema", auth, finding, store)
    rec = suite._base("TRY", "try-it generate_choropleth", auth.public())
    rec.update({"expected": "OK map with a self-contained widget, or a coded error", "arguments": dict(args),
                "inputs": [{"kind": "arguments", "tool": suite.CHOROPLETH_TOOL}]})
    out = mc.call_generate_choropleth(auth.token, args)
    png = suite.apply_choropleth(rec, out)
    html = suite.widget_html(out.get("resources"))
    if rec.get("mcpIsError") is False:
        try:
            disaster = int(str(args.get("disaster_number")).strip())
        except ValueError:
            disaster = None
        pw = args.get("pw_number")
        try:
            pw = int(str(pw).strip()) if pw not in (None, "") else None
        except ValueError:
            pw = None
        suite._finish(rec, *suite.ev_choropleth_ok(rec, disaster, pw=pw))
    elif rec.get("mcpIsError") is True and rec.get("errorCode") in suite.CHOROPLETH_ERROR_CODES:
        # A coded error is a valid answer to a try; show it, do not call it a failure.
        suite._finish(rec, suite.INFO, suite._choropleth_summary(rec))
    else:
        suite._finish(rec, suite.FAIL, suite._choropleth_summary(rec))
    deps = SimpleNamespace(read_trace=make_read_trace(store), sleep=time.sleep, trace_wait_s=(0, 3, 6))
    suite.check_traces([rec], deps, prefixes=("TRY",))
    widgets = {"TRY": html} if html is not None else {}
    res = writer.finish([rec], {"TRY": png} if png else {}, update_latest=False, widgets=widgets)
    return {"res": res, "rec": rec, "html": html, "png": png, "texts": out.get("texts") or [],
            "structured": out.get("structuredContent"), "meta": out.get("meta")}


def try_it(auth: mc.Auth, finding: dict, store: storage.Storage, args: dict, inputs: list):
    writer = RunWriter("try-it", auth, finding, store)
    rec = suite._base("TRY", "try-it generate_diagram", auth.public())
    rec.update({"expected": "PNG + status OK", "inputs": inputs, "arguments": suite._arg_summary(args)})
    out = mc.call_generate_diagram(auth.token, args)
    png = suite.apply_call(rec, out)
    suite._finish(rec, *suite.ev_ok(rec))
    pngs = {"TRY": png} if png else {}
    deps = SimpleNamespace(read_trace=make_read_trace(store), sleep=time.sleep, trace_wait_s=(0, 3, 6))
    suite.check_traces([rec], deps, prefixes=("TRY",))
    res = writer.finish([rec], pngs, update_latest=False)
    return res, rec, png, out.get("meta")
