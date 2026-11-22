"""Tests for the MCP network functions, auth reuse, config, try_it and the V11 setup step
(code review L10). The MCP tests run the real client code (mcp + httpx2) against an
in-process MCP server through httpx2.ASGITransport: no network, no Databricks.
"""

import asyncio
import base64
import json
import unittest
from types import SimpleNamespace

from client import config, runner, storage, suite
from client import mcp_client as mc
from tests.test_report_storage import FakeFiles
from tests.test_suite import fake_png


def fake_lancelot_app():
    """ASGI app: a stateless MCP server with one generate_diagram tool. A fresh server is built
    per request so its lifespan runs in the caller's event loop (each client call uses asyncio.run)."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import CallToolResult, ImageContent, TextContent

    def build():
        srv = MCPServer("fake-lancelot", version="test")

        @srv.tool()
        def generate_diagram(data: str | None = None, fileBase64: str | None = None, fileName: str | None = None,
                             workspacePath: str | None = None, diagramType: str | None = None,
                             hint: str | None = None) -> CallToolResult:
            if data == "bad":
                meta = {"status": "ERROR", "runId": "call-20261105T170102Z-00000e", "errorCode": "INVALID_INPUT",
                        "stage": "input", "message": "bad input"}
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(meta))], is_error=True)
            meta = {"status": "OK", "runId": "call-20261105T170102Z-00000a", "diagramType": "Flowchart"}
            return CallToolResult(content=[
                ImageContent(type="image", data=base64.b64encode(fake_png()).decode(), mime_type="image/png"),
                TextContent(type="text", text=json.dumps(meta))])

        return srv.streamable_http_app(stateless_http=True, json_response=True, transport_security=(
            TransportSecuritySettings(enable_dns_rebinding_protection=False)))

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        inner = build()
        async with inner.router.lifespan_context(inner):
            await inner(scope, receive, send)

    return app


class InProcessMcpTests(unittest.TestCase):
    def setUp(self):
        import httpx2

        self._saved = (mc._TRANSPORT, mc.MCP_URL)
        mc._TRANSPORT = httpx2.ASGITransport(app=fake_lancelot_app())
        mc.MCP_URL = "http://127.0.0.1/mcp"

    def tearDown(self):
        mc._TRANSPORT, mc.MCP_URL = self._saved

    def test_list_tools(self):
        out = mc.list_tools("tok")
        self.assertIsNone(out["error"])
        self.assertEqual(out["serverInfo"]["name"], "fake-lancelot")
        self.assertEqual([t["name"] for t in out["tools"]], ["generate_diagram"])
        self.assertEqual(out["tools"][0]["inputs"], suite.EXPECTED_INPUTS)
        self.assertEqual(out["httpStatus"], 200)
        self.assertTrue(all(isinstance(s, int) for s in out["httpStatuses"]))

    def test_call_ok_returns_png_meta_and_timings(self):
        out = mc.call_generate_diagram("tok", {"data": "x"})
        self.assertIsNone(out["error"])
        self.assertFalse(out["isError"])
        self.assertEqual(out["meta"]["status"], "OK")
        self.assertEqual(base64.b64decode(out["pngBase64"]), fake_png())
        self.assertEqual(out["imageMime"], "image/png")
        # L9: callMs is the request alone and cannot exceed the whole case time
        self.assertIsInstance(out["callMs"], int)
        self.assertLessEqual(out["callMs"], out["ms"])
        rec = suite._base("V5", "t", {"mode": mc.MODE_A})
        suite.apply_call(rec, out)
        self.assertEqual(suite.ev_ok(rec)[0], suite.PASS)

    def test_call_tool_error(self):
        out = mc.call_generate_diagram("tok", {"data": "bad"})
        self.assertIsNone(out["error"])
        self.assertTrue(out["isError"])
        self.assertEqual(out["meta"]["errorCode"], "INVALID_INPUT")

    def test_http_error_is_recorded_not_raised(self):
        mc.MCP_URL = "http://127.0.0.1/not-mcp"
        out = mc.call_generate_diagram("tok", {"data": "x"})
        self.assertIsNotNone(out["error"])
        self.assertIsNone(out["callMs"])
        self.assertEqual(out["httpStatus"], 404)
        self.assertIsNotNone(mc.list_tools("tok")["error"])

    def test_token_not_in_results(self):
        out = mc.call_generate_diagram("secret-token-value", {"data": "x"})
        self.assertNotIn("secret-token-value", json.dumps(out))


class RecordableTests(unittest.TestCase):
    def test_which_errors_are_recorded(self):
        # L4: ordinary errors and cancellation are recorded; interrupts and exits propagate.
        self.assertTrue(mc._recordable(ValueError("x")))
        self.assertTrue(mc._recordable(asyncio.CancelledError()))
        self.assertTrue(mc._recordable(BaseExceptionGroup("g", [asyncio.CancelledError(), ValueError("x")])))
        self.assertFalse(mc._recordable(KeyboardInterrupt()))
        self.assertFalse(mc._recordable(SystemExit(1)))
        self.assertFalse(mc._recordable(BaseExceptionGroup("g", [ValueError("x"), KeyboardInterrupt()])))

    def test_keyboard_interrupt_propagates_from_calls(self):
        orig = mc._with_session

        async def boom(*a, **k):
            raise KeyboardInterrupt
        mc._with_session = boom
        try:
            with self.assertRaises(KeyboardInterrupt):
                mc.call_generate_diagram("t", {})
            with self.assertRaises(KeyboardInterrupt):
                mc.list_tools("t")
        finally:
            mc._with_session = orig


class ReuseAuthTests(unittest.TestCase):
    def test_reuse(self):
        hdr = {"X-Forwarded-Access-Token": "tok-user", "X-Forwarded-Email": "u@x.gov"}
        a = mc.reuse_auth(hdr, {"mode": mc.MODE_A, "note": "n"})
        self.assertEqual((a.mode, a.token, a.caller_email, a.note), (mc.MODE_A, "tok-user", "u@x.gov", "n"))
        self.assertIsNone(mc.reuse_auth({}, {"mode": mc.MODE_A}))
        self.assertIsNone(mc.reuse_auth(hdr, {"mode": None}))
        orig = mc.service_principal_token
        try:
            mc.service_principal_token = lambda: ("tok-sp", "sp-id")
            b = mc.reuse_auth(hdr, {"mode": mc.MODE_B, "note": "forced"})
            self.assertEqual((b.mode, b.token, b.sp_application_id, b.caller_email), (mc.MODE_B, "tok-sp", "sp-id", None))

            def fail():
                raise RuntimeError("no creds")
            mc.service_principal_token = fail
            self.assertIsNone(mc.reuse_auth(hdr, {"mode": mc.MODE_B}))
        finally:
            mc.service_principal_token = orig


class ConfigTests(unittest.TestCase):
    def test_defaults_are_used_everywhere(self):
        self.assertEqual(mc.SERVER_BASE, config.SERVER_BASE)
        self.assertEqual(storage.VOLUME_ROOT, config.VOLUME_ROOT)
        self.assertEqual(suite.OWNER_EMAIL, config.OWNER_EMAIL)
        self.assertEqual(runner.OWNER_V11_PATH, config.OWNER_V11_PATH)
        self.assertTrue(config.OWNER_V11_PATH.startswith(f"/Users/{config.OWNER_EMAIL}/"))

    def test_validate_rejects_bad_values(self):
        saved = {k: getattr(config, k) for k in ("SERVER_BASE", "VOLUME_ROOT", "OWNER_EMAIL", "OWNER_V11_PATH")}
        bad = {"SERVER_BASE": "http://plain.example", "VOLUME_ROOT": "/tmp/x", "OWNER_EMAIL": "nobody",
               "OWNER_V11_PATH": "/Users/someone-else@x.gov/sample.pdf"}
        try:
            for k, v in bad.items():
                setattr(config, k, v)
                with self.assertRaises(ValueError, msg=k):
                    config.validate()
                setattr(config, k, saved[k])
            config.validate()
        finally:
            for k, v in saved.items():
                setattr(config, k, v)


class MessagePolicyTests(unittest.TestCase):
    def test_message_kept_only_for_request_errors(self):
        # L6
        text, info = suite.message_record("ACCESS_DENIED", "workspacePath must be inside your own folder")
        self.assertEqual(text, "workspacePath must be inside your own folder")
        self.assertTrue(info["stored"])
        text, info = suite.message_record("EXTRACTION_FAILED", "could not parse 'Pikachu line 3'")
        self.assertIsNone(text)
        self.assertEqual(info, {"chars": 32, "sha256": suite.sha256(b"could not parse 'Pikachu line 3'"),
                                "stored": False})
        self.assertEqual(suite.message_record("INVALID_INPUT", "x" * 1000)[0], "x" * suite.MESSAGE_MAX_CHARS)
        self.assertEqual(suite.message_record(None, None), (None, None))

    def test_apply_call_never_stores_other_messages(self):
        rec = suite._base("V6", "t", {})
        suite.apply_call(rec, {"isError": True, "meta": {"status": "ERROR", "errorCode": "LLM_TIMEOUT",
                                                         "message": "secret doc words"}})
        self.assertIsNone(rec["message"])
        self.assertNotIn("secret doc words", json.dumps(rec))
        self.assertEqual(rec["messageInfo"]["chars"], len("secret doc words"))


class TryFemaTests(unittest.TestCase):
    def run_try(self, out, args):
        files = FakeFiles()
        rid = "call-20261106T170102Z-0000bb"
        files.data[storage.server_trace_path(rid)] = json.dumps({"run": {"outcome": "OK" if not out["isError"] else out["meta"]["errorCode"]}}).encode()
        out["meta"]["runId"] = rid
        store = storage.Storage(SimpleNamespace(files=files))
        orig = mc.call_generate_choropleth
        mc.call_generate_choropleth = lambda token, a: dict(out, httpStatus=200, ms=500, callMs=400)
        try:
            auth = mc.Auth(mc.MODE_A, "secret-token-value", suite.OWNER_EMAIL, None, "ok")
            got = runner.try_fema(auth, {}, store, args)
        finally:
            mc.call_generate_choropleth = orig
        for blob in files.data.values():
            self.assertNotIn(b"secret-token-value", blob)
        return got, files

    def test_ok_map_is_saved_and_checked(self):
        html = ("<!doctype html><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'\">"
                "<script>draw()</script>")
        png = fake_png(1000, 1000)
        out = {"isError": False, "meta": {"status": "OK"}, "texts": ["DR-4856: 5 outliers"],
               "pngBase64": base64.b64encode(png).decode(), "imageMime": "image/png",
               "structuredContent": {"status": "OK", "disasterNumber": 4856, "totals": {"outliers": 5},
                                     "highlight": {"pw": 2, "flagged": True}, "map": {"drawn": True},
                                     "image": {"sha256": __import__("hashlib").sha256(png).hexdigest(), "mapDrawn": True}},
               "resources": [{"uri": "ui://lancelot-beta/choropleth/c.html", "mimeType": "text/html", "text": html}]}
        got, files = self.run_try(out, {"disaster_number": "4856", "pw_number": "2"})
        rec, res = got["rec"], got["res"]
        self.assertEqual((rec["verdict"], got["html"], got["texts"]), (suite.PASS, html, ["DR-4856: 5 outliers"]))
        self.assertEqual(rec["serverTrace"]["match"], True)
        self.assertEqual(res["kind"], "try-fema")
        d = res["storage"]["runDir"]
        self.assertEqual(sorted(p.rsplit("/", 1)[1] for p in files.data if p.startswith(d)),
                         ["TRY.png", "TRY.widget.html", "report.html", "result.json"])
        self.assertEqual(files.data[f"{d}/TRY.widget.html"], html.encode())
        self.assertEqual(files.data[f"{d}/TRY.png"], png)
        self.assertEqual((got["png"], rec["image"]["shaMatches"], rec["png"]["file"]), (png, True, "TRY.png"))
        self.assertFalse(any(p.startswith(storage.LATEST_DIR) for p in files.data))
        # a different highlighted PW than asked for is a FAIL
        got, _ = self.run_try(out, {"disaster_number": 4856, "pw_number": 3})
        self.assertEqual(got["rec"]["verdict"], suite.FAIL)

    def test_coded_error_is_info_unknown_code_is_fail(self):
        out = {"isError": True, "meta": {"status": "ERROR", "errorCode": "DISASTER_NOT_LOADED", "stage": "data",
                                        "message": "not loaded"}, "resources": []}
        got, files = self.run_try(out, {"disaster_number": 1})
        self.assertEqual((got["rec"]["verdict"], got["html"]), (suite.INFO, None))
        self.assertFalse(any(p.endswith(".widget.html") for p in files.data))
        out["meta"]["errorCode"] = "SOMETHING_NEW"
        got, _ = self.run_try(out, {"disaster_number": 1})
        self.assertEqual(got["rec"]["verdict"], suite.FAIL)


class TryItTests(unittest.TestCase):
    def test_try_it_writes_run_and_checks_trace(self):
        files = FakeFiles()
        rid = "call-20261105T170102Z-0000aa"
        files.data[storage.server_trace_path(rid)] = json.dumps({"run": {"outcome": "OK"}}).encode()
        store = storage.Storage(SimpleNamespace(files=files))
        orig = mc.call_generate_diagram
        mc.call_generate_diagram = lambda token, args: {
            "isError": False, "meta": {"status": "OK", "runId": rid, "diagramType": "Flowchart"},
            "pngBase64": base64.b64encode(fake_png()).decode(), "httpStatus": 200, "ms": 900, "callMs": 800}
        try:
            auth = mc.Auth(mc.MODE_B, "secret-token-value", None, "sp-id", "forced")
            res, rec, png, meta = runner.try_it(auth, {"forcedModeB": True}, store, {"data": "hello"},
                                                [suite.input_desc("data", None, b"hello")])
        finally:
            mc.call_generate_diagram = orig
        self.assertEqual(rec["verdict"], suite.PASS)
        self.assertEqual(png, fake_png())
        self.assertEqual(meta["runId"], rid)
        self.assertEqual(rec["serverTrace"]["match"], True)
        self.assertEqual(rec["callMs"], 800)
        names = sorted(p.rsplit("/", 1)[1] for p in files.data if p.startswith(res["storage"]["runDir"]))
        self.assertEqual(names, ["TRY.png", "report.html", "result.json"])
        self.assertFalse(any(p.startswith(storage.LATEST_DIR) for p in files.data))  # try-it never updates latest/
        for blob in files.data.values():
            self.assertNotIn(b"secret-token-value", blob)
            self.assertNotIn(b"hello", blob)  # document text is never written
        saved = json.loads(files.data[f"{res['storage']['runDir']}/result.json"])
        self.assertEqual(saved["cases"][0]["arguments"], {"data": "<5 chars>"})


class VersionsTests(unittest.TestCase):
    def test_versions_reports_lock_file(self):
        v = runner.versions()
        self.assertRegex(v["requirementsSha256"] or "", r"^[0-9a-f]{64}$")
        self.assertIn("pinsMatchInstalled", v)
        self.assertIsInstance(v["pinMismatches"], list)


if __name__ == "__main__":
    unittest.main()
