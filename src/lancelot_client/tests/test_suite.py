"""Unit tests for the suite run loop and evaluators. No network.

Run: PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -t .
"""

import base64
import hashlib
import struct
import unittest
from types import SimpleNamespace

from client import mcp_client as mc
from client import suite


def fake_png(w=120, h=80) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"\x00" * 20


class FakeServer:
    """Behaves like a healthy mcp-lancelot-beta."""

    def __init__(self, caller_email=None):
        self.n = 0
        self.traces = {}
        self.caller_email = caller_email
        self.calls = []

    def http_get(self, path):
        if path == "/health":
            return {"httpStatus": 200, "json": {"status": "ok", "phase": 2, "tools": list(suite.EXPECTED_TOOLS)}, "ms": 5}
        if path == "/api/selftest-obo-scope":
            return {"httpStatus": 200, "json": {"forwardedTokenPresent": True, "forwardedEmail": self.caller_email,
                                                "probe": {"httpStatus": 200}}, "ms": 5}
        if path == "/mcp":
            return {"httpStatus": 405, "json": None, "ms": 3}
        return {"httpStatus": 404, "ms": 1}

    def list_tools(self):
        return {"tools": [{"name": "generate_diagram", "inputs": list(suite.EXPECTED_INPUTS)},
                          {"name": "generate_choropleth", "inputs": list(suite.CHOROPLETH_INPUTS)}], "httpStatus": 200, "ms": 9}

    def call_choropleth(self, args):
        """Like the real tool: loaded disasters 4856 and 4673 in snapshot 2026-11-06."""
        self.calls.append(args)
        rid = self._run_id()
        try:
            dn = int(args.get("disaster_number"))
        except (TypeError, ValueError):
            return self._err(rid, "INVALID_INPUT", "input")
        sigma = args.get("sigma_threshold", 3)
        if not 1 <= float(sigma) <= 10:
            return self._err(rid, "INVALID_INPUT", "input")
        if args.get("as_of") not in (None, "2026-11-06"):
            return self._err(rid, "SNAPSHOT_NOT_FOUND", "data")
        if dn not in (4856, 4673):
            return self._err(rid, "DISASTER_NOT_LOADED", "data")
        pw = args.get("pw_number")
        if pw is not None and int(pw) > 5000:
            return self._err(rid, "PW_NOT_FOUND", "analysis")
        self.traces[rid] = {"run": {"outcome": "OK"}}
        sc = {"status": "OK", "runId": rid, "disasterNumber": dn, "snapshotDate": "2026-11-06", "sigmaThreshold": 3,
              "totals": {"projectsAll": 300, "projectsMapped": 295, "outliers": 5, "outlierCounties": 3,
                         "statewideOutliers": 1, "unmappable": 5, "unmappableOutliers": 0},  # server analysis.totals shape
              "highlight": {"pw": int(pw), "flagged": True} if pw else None,
              "map": {"drawn": True, "countiesNotInShapes": []}}
        png = fake_png(1000, 1000)  # D44 square image
        sc["image"] = {"mimeType": "image/png", "width": 1000, "height": 1000, "sha256": hashlib.sha256(png).hexdigest(),
                       "mapDrawn": True, "reason": None, "title": f"DR-{dn}-XX Test", "affectedDrawn": 3}
        html = self.widget_html
        return {"isError": False, "meta": {"status": "OK", "runId": rid}, "structuredContent": sc,
                "pngBase64": base64.b64encode(png).decode(), "imageMime": "image/png",
                "resources": [{"uri": f"ui://lancelot-beta/choropleth/{rid}.html", "mimeType": "text/html", "text": html}],
                "httpStatus": 200, "ms": 400}

    widget_html = ('<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
                   'script-src \'unsafe-inline\'"><svg xmlns="http://www.w3.org/2000/svg"></svg><script>1</script>')

    def _run_id(self):
        self.n += 1
        return f"call-20261105T170102Z-{self.n:06x}"

    def call_tool(self, args):
        self.calls.append(args)
        rid = self._run_id()
        sources = [k for k in ("data", "fileBase64", "workspacePath") if k in args]
        if len(sources) != 1:
            return self._err(rid, "INVALID_INPUT", "input")
        wp = args.get("workspacePath")
        if wp and not wp.lower().startswith(f"/users/{(self.caller_email or 'sp-id').lower()}/"):
            return self._err(rid, "ACCESS_DENIED", "input")
        dt = args.get("diagramType")
        dtype, select = ("Sequence diagram", 0) if dt == "Sequence diagram" else ("Flowchart", 1200)
        self.traces[rid] = {"run": {"outcome": "OK"}}
        meta = {"status": "OK", "runId": rid, "diagramType": dtype, "timingsMs": {"select": select}, "width": 120, "height": 80}
        return {"isError": False, "meta": meta, "pngBase64": base64.b64encode(fake_png()).decode(), "httpStatus": 200, "ms": 1000}

    def _err(self, rid, code, stage):
        self.traces[rid] = {"run": {"outcome": code}}
        return {"isError": True, "meta": {"status": "ERROR", "runId": rid, "errorCode": code, "stage": stage, "message": "x"},
                "pngBase64": None, "httpStatus": 200, "ms": 50}

    def read_trace(self, rid):
        t = self.traces.get(rid)
        return (t, None) if t else (None, "NOT_FOUND")


SAMPLES = {"synthetic_workflow.json": b'{"a":1}', "sample.pdf": b"%PDF-1.4 fake", "sample.docx": b"PK docx",
           "sample.xlsx": b"PK xlsx", "synthetic_sequence.txt": b"A asks B", "synthetic_mindmap.txt": b"ideas"}


def deps_for(server, auth, samples=SAMPLES):
    return suite.SuiteDeps(auth=auth, http_get=server.http_get, list_tools=server.list_tools, call_tool=server.call_tool,
                           read_trace=server.read_trace, load_sample=samples.get,
                           call_choropleth=server.call_choropleth, sleep=lambda s: None)


class RunSuiteTests(unittest.TestCase):
    def test_healthy_server_mode_a_all_pass(self):
        email = suite.OWNER_EMAIL
        srv = FakeServer(caller_email=email)
        auth = {"mode": mc.MODE_A, "callerEmail": email}
        run = suite.run_suite(deps_for(srv, auth))
        ids = [c["id"] for c in run.cases]
        self.assertEqual(ids, [cid for cid, _ in suite.CASES])
        self.assertFalse({"C2", "V11"} & set(ids))  # removed 2026-11-12: must never be expected to work
        verdicts = {c["id"]: c["verdict"] for c in run.cases}
        self.assertTrue(all(v == suite.PASS for v in verdicts.values()), verdicts)
        # V12 in Mode A as the owner points at a fake other user
        v12 = next(c for c in run.cases if c["id"] == "V12")
        self.assertEqual(v12["arguments"]["workspacePath"], suite.V12_OTHER_USER_PATH)
        # every V case with a runId got a trace check
        t1 = run.cases[-1]
        self.assertEqual(len(t1["traces"]), 16)  # V5 V6 V7a V7b V8 V9 V10a V10b V12 V14 M1-M6
        m1 = next(c for c in run.cases if c["id"] == "M1")
        self.assertEqual((m1["choropleth"]["highlightPw"], m1["widget"]["csp"], m1["widget"]["externalUrls"]), (2, True, []))
        c = m1["choropleth"]
        self.assertEqual([c[k] for k in ("projects", "projectsMapped", "unmappable", "outlierCounties", "statewideOutliers")],
                         [300, 295, 5, 3, 1])
        self.assertIn("projects=300 (mapped 295)", m1["actual"])
        self.assertNotIn("text", m1["widget"])  # the record keeps checks only; the HTML is in run.widgets (D19)
        self.assertEqual(sorted(run.widgets), ["M1", "M2"])  # error cases return no widget
        self.assertEqual(run.widgets["M1"], FakeServer.widget_html)
        self.assertEqual(next(c for c in run.cases if c["id"] == "M2")["arguments"], {"disaster_number": "4673"})
        self.assertIn("V6", run.pngs)
        self.assertEqual(next(c for c in run.cases if c["id"] == "V6")["png"], {"width": 120, "height": 80, "bytes": len(fake_png())})

    def test_no_document_text_in_records(self):
        srv = FakeServer(caller_email=suite.OWNER_EMAIL)
        run = suite.run_suite(deps_for(srv, {"mode": mc.MODE_A, "callerEmail": suite.OWNER_EMAIL}))
        blob = repr(run.cases)
        for secret in ("A asks B", "%PDF-1.4 fake", "Pallet Town"):
            self.assertNotIn(secret, blob)
        v5 = next(c for c in run.cases if c["id"] == "V5")
        self.assertEqual(v5["arguments"]["data"], "<7 chars>")
        self.assertEqual(v5["inputs"][0]["sha256"], suite.sha256(SAMPLES["synthetic_workflow.json"]))

    def test_mode_b_labels_and_v12_targets_owner(self):
        srv = FakeServer(caller_email=None)
        auth = {"mode": mc.MODE_B, "callerEmail": None}
        run = suite.run_suite(deps_for(srv, auth))
        v12 = next(c for c in run.cases if c["id"] == "V12")
        self.assertIn("Mode B", v12["note"])
        self.assertTrue(v12["arguments"]["workspacePath"].startswith(f"/Users/{suite.OWNER_EMAIL}/"))
        self.assertEqual(v12["verdict"], suite.PASS)

    def test_missing_sample_fails_without_calling(self):
        srv = FakeServer(caller_email=suite.OWNER_EMAIL)
        samples = {k: v for k, v in SAMPLES.items() if k != "sample.docx"}
        run = suite.run_suite(deps_for(srv, {"mode": mc.MODE_A, "callerEmail": suite.OWNER_EMAIL}, samples=samples))
        v7a = next(c for c in run.cases if c["id"] == "V7a")
        self.assertEqual(v7a["verdict"], suite.FAIL)
        self.assertIn("sample missing", v7a["actual"])
        self.assertFalse(any(a.get("fileName") == "sample.docx" for a in srv.calls))

    def test_t1_detects_missing_and_mismatched_traces(self):
        srv = FakeServer(caller_email=suite.OWNER_EMAIL)
        orig = srv.call_tool

        def call(args):
            out = orig(args)
            rid = out["meta"]["runId"]
            if srv.n == 1:
                del srv.traces[rid]  # never written
            if srv.n == 2:
                srv.traces[rid] = {"run": {"outcome": "LLM_ERROR"}}  # disagrees with OK
            return out
        srv.call_tool = call
        waits = []
        d = deps_for(srv, {"mode": mc.MODE_A, "callerEmail": suite.OWNER_EMAIL})
        d.sleep = waits.append
        run = suite.run_suite(d)
        t1 = run.cases[-1]
        self.assertEqual(t1["verdict"], suite.FAIL)
        self.assertIn("V5: found=False", t1["actual"])
        self.assertIn("V6: found=True outcome='LLM_ERROR'", t1["actual"])
        self.assertEqual(waits, [3, 6, 10])  # retried only the missing one

    def test_transport_error_fails(self):
        srv = FakeServer(caller_email=suite.OWNER_EMAIL)
        srv.call_tool = lambda args: {"isError": None, "meta": None, "pngBase64": None, "error": "ReadTimeout", "ms": 130000}
        srv.call_choropleth = srv.call_tool
        run = suite.run_suite(deps_for(srv, {"mode": mc.MODE_A, "callerEmail": suite.OWNER_EMAIL}))
        for c in run.cases:
            if c["id"].startswith(("V", "M")) and c["id"] != "V4":
                self.assertEqual(c["verdict"], suite.FAIL, c["id"])
        self.assertEqual(run.cases[-1]["actual"], "no V or M case returned a runId")


class EvaluatorTests(unittest.TestCase):
    def rec(self, **kw):
        base = {"mcpIsError": False, "status": "OK", "png": {"width": 1, "height": 1, "bytes": 1}, "clientMs": 1000,
                "diagramType": "Flowchart", "timingsMs": {"select": 900}}
        base.update(kw)
        return base

    def test_health(self):
        ok = {"httpStatus": 200, "json": {"phase": 2, "tools": ["generate_diagram", "generate_choropleth"]}}
        self.assertEqual(suite.ev_health(ok)[0], suite.PASS)
        self.assertEqual(suite.ev_health({"httpStatus": 302})[0], suite.FAIL)
        self.assertEqual(suite.ev_health({"httpStatus": 200, "json": {"phase": 1, "tools": ["generate_diagram"]}})[0], suite.FAIL)
        self.assertEqual(suite.ev_health({"httpStatus": 200, "json": {"phase": 2, "tools": ["generate_diagram", "x"]}})[0], suite.FAIL)
        # the old one-tool server now fails C1
        self.assertEqual(suite.ev_health({"httpStatus": 200, "json": {"phase": 2, "tools": ["generate_diagram"]}})[0], suite.FAIL)

    def test_get_mcp(self):
        self.assertEqual(suite.ev_get_mcp({"httpStatus": 405})[0], suite.PASS)
        self.assertEqual(suite.ev_get_mcp({"httpStatus": 200})[0], suite.FAIL)

    def test_tools(self):
        good = {"tools": [{"name": "generate_diagram", "inputs": list(suite.EXPECTED_INPUTS)},
                          {"name": "generate_choropleth", "inputs": list(suite.CHOROPLETH_INPUTS)}]}
        self.assertEqual(suite.ev_tools(good)[0], suite.PASS)
        self.assertEqual(suite.ev_tools({"tools": good["tools"][::-1]})[0], suite.PASS)
        extra = {"tools": good["tools"] + [{"name": "x", "inputs": []}]}
        self.assertEqual(suite.ev_tools(extra)[0], suite.FAIL)
        self.assertEqual(suite.ev_tools({"tools": good["tools"][:1]})[0], suite.FAIL)  # old server
        missing = {"tools": [{"name": "generate_diagram", "inputs": ["data"]}, good["tools"][1]]}
        self.assertEqual(suite.ev_tools(missing)[0], suite.FAIL)
        no_asof = {"tools": [good["tools"][0], {"name": "generate_choropleth", "inputs": ["disaster_number"]}]}
        self.assertEqual(suite.ev_tools(no_asof)[0], suite.FAIL)
        self.assertEqual(suite.ev_tools({"tools": None, "error": "boom"})[0], suite.FAIL)

    def test_ok_variants(self):
        self.assertEqual(suite.ev_ok(self.rec())[0], suite.PASS)
        self.assertEqual(suite.ev_ok(self.rec(png=None))[0], suite.FAIL)
        self.assertEqual(suite.ev_ok(self.rec(clientMs=75_000), max_ms=75_000)[0], suite.FAIL)
        self.assertEqual(suite.ev_ok(self.rec(diagramType="Sequence diagram", timingsMs={"select": 0}),
                                     want_type="Sequence diagram", select_zero=True)[0], suite.PASS)
        self.assertEqual(suite.ev_ok(self.rec(diagramType="Sequence diagram"), want_type="Sequence diagram",
                                     select_zero=True)[0], suite.FAIL)
        self.assertEqual(suite.ev_ok(self.rec(diagramType="Mindmap"), not_type="Mindmap")[0], suite.FAIL)

    def test_error_and_v14(self):
        err = {"mcpIsError": True, "errorCode": "INVALID_INPUT", "clientMs": 10}
        self.assertEqual(suite.ev_error(err, "INVALID_INPUT")[0], suite.PASS)
        self.assertEqual(suite.ev_error(err, "ACCESS_DENIED")[0], suite.FAIL)
        self.assertEqual(suite.ev_v14(dict(err, errorCode="LLM_TIMEOUT", clientMs=70_000))[0], suite.PASS)
        self.assertEqual(suite.ev_v14(dict(err, errorCode="LLM_TIMEOUT", clientMs=80_000))[0], suite.FAIL)
        self.assertEqual(suite.ev_v14({"transportError": "RemoteProtocolError", "clientMs": 5})[0], suite.FAIL)
        self.assertEqual(suite.ev_v14(self.rec())[0], suite.PASS)

    def test_choropleth_evaluators(self):
        html = FakeServer.widget_html
        ok = {"mcpIsError": False, "status": "OK",
              "choropleth": {"disasterNumber": 4856, "outliers": 5, "mapDrawn": True, "highlightPw": 2},
              "widget": suite.widget_info([{"uri": "ui://x/1.html", "mimeType": "text/html", "text": html}])}
        png = fake_png(1000, 1000)
        ok["image"] = suite.image_info(png, {"image": {"sha256": hashlib.sha256(png).hexdigest(), "mapDrawn": True}})
        self.assertEqual(suite.ev_choropleth_ok(ok, 4856, pw=2)[0], suite.PASS)
        # D44: no image, a wrong size, or a sha mismatch is a FAIL
        self.assertEqual(suite.ev_choropleth_ok(dict(ok, image=None), 4856)[0], suite.FAIL)
        small = fake_png(800, 800)
        self.assertEqual(suite.ev_choropleth_ok(dict(ok, image=suite.image_info(small, {"image": {"sha256": hashlib.sha256(small).hexdigest()}})), 4856)[0], suite.FAIL)
        self.assertEqual(suite.ev_choropleth_ok(dict(ok, image=suite.image_info(png, {"image": {"sha256": "0" * 64}})), 4856)[0], suite.FAIL)
        self.assertEqual(suite.ev_choropleth_error(dict(ok, mcpIsError=True, errorCode="X", widget=None), "X")[0], suite.FAIL)  # image present
        self.assertEqual(suite.ev_choropleth_ok(ok, 4673)[0], suite.FAIL)
        self.assertEqual(suite.ev_choropleth_ok(ok, 4856, pw=3)[0], suite.FAIL)
        cdn = html + '<script src="https://cdn.jsdelivr.net/npm/us-atlas@3/counties-10m.json"></script>'
        bad = dict(ok, widget=suite.widget_info([{"uri": "ui://x/1.html", "mimeType": "text/html", "text": cdn}]))
        self.assertEqual(bad["widget"]["externalUrls"], ["https://cdn.jsdelivr.net/npm/us-atlas@3/counties-10m.json"])
        self.assertEqual(suite.ev_choropleth_ok(bad, 4856)[0], suite.FAIL)
        no_csp = dict(ok, widget=suite.widget_info([{"uri": "ui://x", "mimeType": "text/html", "text": "<svg></svg>"}]))
        self.assertEqual(suite.ev_choropleth_ok(no_csp, 4856)[0], suite.FAIL)
        self.assertEqual(suite.ev_choropleth_ok(dict(ok, widget=None), 4856)[0], suite.FAIL)
        self.assertEqual(suite.ev_choropleth_ok(dict(ok, choropleth=dict(ok["choropleth"], mapDrawn=False)), 4856)[0], suite.FAIL)
        self.assertIsNone(suite.widget_info([{"mimeType": "text/plain", "text": "x"}]))
        err = {"mcpIsError": True, "errorCode": "DISASTER_NOT_LOADED", "widget": None}
        self.assertEqual(suite.ev_choropleth_error(err, "DISASTER_NOT_LOADED")[0], suite.PASS)
        self.assertEqual(suite.ev_choropleth_error(err, "PW_NOT_FOUND")[0], suite.FAIL)

    def test_map_cases_skip_without_caller(self):
        d = deps_for(FakeServer(caller_email=suite.OWNER_EMAIL), {"mode": mc.MODE_A, "callerEmail": suite.OWNER_EMAIL})
        d.call_choropleth = None
        run = suite.run_suite(d)
        self.assertEqual({c["verdict"] for c in run.cases if c["id"].startswith("M")}, {suite.SKIP})

    def test_png_info_and_long_text(self):
        self.assertEqual(suite.png_info(fake_png(2400, 1843))["width"], 2400)
        self.assertIsNone(suite.png_info(b"GIF89a"))
        t = suite.synthetic_long_text()
        self.assertEqual(len(t), 60_000)
        self.assertEqual(t, suite.synthetic_long_text())


class McpClientPureTests(unittest.TestCase):
    def test_parse_call_result(self):
        res = SimpleNamespace(is_error=False, content=[
            SimpleNamespace(type="image", data="QUJD", mime_type="image/png"),
            SimpleNamespace(type="text", text='{"status": "OK", "runId": "call-x"}')])
        out = mc.parse_call_result(res)
        self.assertEqual((out["isError"], out["pngBase64"], out["imageMime"], out["meta"]["status"]),
                         (False, "QUJD", "image/png", "OK"))
        bad = mc.parse_call_result(SimpleNamespace(is_error=True, content=[SimpleNamespace(type="text", text="nope")]))
        self.assertTrue(bad["isError"])
        self.assertIn("not JSON", bad["metaParseError"])
        # generate_choropleth: summary text, then the widget resource, then the JSON
        res = SimpleNamespace(is_error=False, structured_content={"status": "OK", "disasterNumber": 4856}, content=[
            SimpleNamespace(type="text", text="DR-4856: 5 outliers"),
            SimpleNamespace(type="resource", resource=SimpleNamespace(uri="ui://lancelot-beta/choropleth/c.html",
                                                                      mime_type="text/html", text="<html></html>")),
            SimpleNamespace(type="text", text='{"status": "OK", "runId": "call-y"}')])
        out = mc.parse_call_result(res)
        self.assertEqual(out["meta"]["runId"], "call-y")
        self.assertIsNone(out["metaParseError"])
        self.assertEqual(out["resources"], [{"uri": "ui://lancelot-beta/choropleth/c.html", "mimeType": "text/html",
                                             "text": "<html></html>"}])
        self.assertEqual(out["structuredContent"]["disasterNumber"], 4856)

    def test_resolve_auth_mode_a_and_rejection(self):
        hdr = {"X-Forwarded-Access-Token": "tok-user", "X-Forwarded-Email": "u@x.gov"}
        auth, finding = mc.resolve_auth(hdr, probe=lambda p, t: {"httpStatus": 200, "ms": 1})
        self.assertEqual((auth.mode, auth.caller_email), (mc.MODE_A, "u@x.gov"))
        self.assertNotIn("tok-user", repr(auth.public()) + repr(finding))
        orig = mc.service_principal_token
        mc.service_principal_token = lambda: ("tok-sp", "sp-app-id")
        try:
            auth, finding = mc.resolve_auth(hdr, probe=lambda p, t: {"httpStatus": 401, "ms": 1})
            self.assertEqual(auth.mode, mc.MODE_B)
            self.assertTrue(finding["modeARejected"])
            self.assertIn("HTTP 401", auth.note)
            blob = repr(auth.public()) + repr(finding)
            self.assertNotIn("tok-user", blob)
            self.assertNotIn("tok-sp", blob)
            auth, finding = mc.resolve_auth({}, probe=lambda p, t: self.fail("no probe without token"))
            self.assertEqual(auth.mode, mc.MODE_B)
            # Force Mode B: user token present but never probed or used
            auth, finding = mc.resolve_auth(hdr, probe=lambda p, t: self.fail("forced B must not probe"),
                                            force_mode_b=True)
            self.assertEqual((auth.mode, auth.token, auth.caller_email), (mc.MODE_B, "tok-sp", None))
            self.assertTrue(finding["forcedModeB"])
            self.assertTrue(finding["userTokenForwarded"])
            self.assertIn("forced", auth.note)
            self.assertNotIn("tok-user", repr(auth.public()) + repr(finding))
        finally:
            mc.service_principal_token = orig


if __name__ == "__main__":
    unittest.main()
