"""Unit tests for report building and storage paths/writes. No network."""

import io
import json
import re
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from client import mcp_client as mc
from client import report, runner, storage, suite
from tests.test_suite import fake_png


class StoragePathTests(unittest.TestCase):
    def test_ids_and_paths(self):
        now = datetime(2026, 11, 5, 17, 1, 2, tzinfo=timezone.utc)
        rid = storage.new_client_run_id(now, "a1b2c3")
        self.assertEqual(rid, "client-20261105T170102Z-a1b2c3")
        self.assertEqual(storage.run_dir(rid), f"{storage.CLIENT_ROOT}/2026-11-05/{rid}")
        self.assertRegex(storage.new_client_run_id(), r"^client-\d{8}T\d{6}Z-[0-9a-f]{6}$")
        with self.assertRaises(ValueError):
            storage.run_dir("../runs/x")

    def test_server_trace_path(self):
        self.assertEqual(storage.server_trace_path("call-20261105T170102Z-a1b2c3"),
                         f"{storage.VOLUME_ROOT}/runs/2026-11-05/call-20261105T170102Z-a1b2c3/trace.json")
        self.assertIsNone(storage.server_trace_path("../../etc"))
        self.assertIsNone(storage.server_trace_path(""))

    def test_refuses_server_areas(self):
        for bad in (f"{storage.VOLUME_ROOT}/runs/2026-11-05/x.json", f"{storage.VOLUME_ROOT}/latest/report.html",
                    f"{storage.CLIENT_ROOT}/../runs/x", f"{storage.CLIENT_ROOT}", "/tmp/x"):
            with self.assertRaises(ValueError, msg=bad):
                storage.assert_client_path(bad)
        storage.assert_client_path(f"{storage.LATEST_DIR}/summary.json")


class FakeFiles:
    """In-memory Files API. fail=True fails every upload; fail_paths fails uploads whose path ends
    with one of the given suffixes; download raises the SDK's typed NotFound like the real API."""

    def __init__(self, fail=False, fail_paths=()):
        self.data, self.fail, self.fail_paths = {}, fail, tuple(fail_paths)

    def upload(self, path, fh, overwrite=False):
        if self.fail or (self.fail_paths and path.endswith(self.fail_paths)):
            raise PermissionError("PERMISSION_DENIED: no WRITE_VOLUME")
        self.data[path] = fh.read()

    def download(self, path):
        from databricks.sdk.errors import NotFound

        if path not in self.data:
            raise NotFound(f"The file {path} does not exist")
        return SimpleNamespace(contents=io.BytesIO(self.data[path]))


class StorageWriteTests(unittest.TestCase):
    def test_write_and_read_back(self):
        files = FakeFiles()
        s = storage.Storage(SimpleNamespace(files=files))
        p = f"{storage.CLIENT_ROOT}/2026-11-05/client-20261105T170102Z-a1b2c3/result.json"
        self.assertTrue(s.write_json(p, {"a": 1}))
        self.assertEqual(s.read_json(p), ({"a": 1}, None))
        self.assertEqual(s.read_json(p + ".missing"), (None, "NOT_FOUND"))
        self.assertFalse(s.write_bytes(f"{storage.VOLUME_ROOT}/runs/x", b"x"))
        self.assertEqual(len(s.errors), 1)
        self.assertNotIn(f"{storage.VOLUME_ROOT}/runs/x", files.data)

    def test_read_errors_other_than_404_are_not_not_found(self):
        # L5: a message that merely mentions 404 or 'does not exist' is a real error, not NOT_FOUND.
        class Broken:
            def download(self, path):
                raise PermissionError("403: user does not exist in group; see doc 404")
        s = storage.Storage(SimpleNamespace(files=Broken()))
        obj, err = s.read_json(f"{storage.VOLUME_ROOT}/runs/x/trace.json")
        self.assertIsNone(obj)
        self.assertNotEqual(err, "NOT_FOUND")
        self.assertIn("PermissionError", err)

    def test_failure_is_recorded_not_raised(self):
        s = storage.Storage(SimpleNamespace(files=FakeFiles(fail=True)))
        self.assertFalse(s.write_bytes(f"{storage.CLIENT_ROOT}/latest/report.html", b"x"))
        self.assertIn("PERMISSION_DENIED", s.errors[0]["error"])


def sample_cases():
    return [
        {"id": "V5", "title": "<script>alert(1)</script>", "verdict": "PASS", "expected": "ok & <b>",
         "actual": "\"quoted\" <img src=x onerror=1>", "clientMs": 10, "serverRunId": "call-20261105T170102Z-a1b2c3",
         "note": "<a href='https://evil.example'>x</a>", "serverTrace": {"found": True, "outcome": "OK", "match": True}},
        {"id": "V10a", "title": "no input", "verdict": "FAIL", "expected": "x", "actual": "y"},
    ]


class ReportTests(unittest.TestCase):
    def build(self, errors=()):
        return report.build_result(
            client_run_id="client-20261105T170102Z-a1b2c3", kind="suite", started_at="s", finished_at="f",
            auth={"mode": mc.MODE_A, "note": "<i>n</i>"}, auth_finding={"userTokenForwarded": True},
            cases=sample_cases(), versions={"mcp": "2.3.0"}, storage_errors=list(errors),
            run_dir="/Volumes/x", server_base=mc.SERVER_BASE)

    def test_result_summary(self):
        r = self.build()
        self.assertEqual(r["summary"], {"PASS": 1, "FAIL": 1, "INFO": 0, "SKIP": 0})
        s = report.summary_of(r)
        self.assertEqual([c["id"] for c in s["cases"]], ["V5", "V10a"])
        json.dumps(r)

    def test_html_is_escaped_and_script_free(self):
        page = report.render_html(self.build(errors=[{"path": "p", "error": "<e>"}]), {"V5": fake_png()})
        low = page.lower()
        self.assertNotIn("<script", low)
        self.assertNotIn("<a ", low)
        self.assertNotRegex(low, r"<[^>]*\shref\s*=")  # escaped text may mention href; no real attribute
        self.assertNotIn("onerror=1>", low)
        self.assertNotIn("<i>n</i>", page)
        self.assertIn("&lt;script&gt;", page)
        # every <img> is an inline data URI
        srcs = re.findall(r'<img[^>]*src="([^"]*)"', page)
        self.assertEqual(len(srcs), 1)
        self.assertTrue(srcs[0].startswith("data:image/png;base64,"))
        self.assertNotRegex(page, r'src="https?:')
        self.assertIn("Storage errors", page)


class RunWriterTests(unittest.TestCase):
    def auth(self):
        return mc.Auth(mc.MODE_A, "secret-token-value", suite.OWNER_EMAIL, None, "note")

    def test_writes_run_files_and_latest_without_token(self):
        files = FakeFiles()
        s = storage.Storage(SimpleNamespace(files=files))
        w = runner.RunWriter("suite", self.auth(), {"userTokenForwarded": True}, s)
        cases = [dict(sample_cases()[0], png={"width": 120, "height": 80, "bytes": 10})]
        res = w.finish(cases, {"V5": fake_png()}, update_latest=True)
        names = sorted(p.rsplit("/", 1)[1] for p in files.data if p.startswith(w.dir))
        self.assertEqual(names, ["V5.png", "report.html", "result.json"])
        self.assertIn(f"{storage.LATEST_DIR}/summary.json", files.data)
        self.assertIn(f"{storage.LATEST_DIR}/report.html", files.data)
        self.assertFalse(any("/runs/" in p for p in files.data))
        for blob in files.data.values():
            self.assertNotIn(b"secret-token-value", blob)
        saved = json.loads(files.data[f"{w.dir}/result.json"])
        self.assertEqual(saved["cases"][0]["png"]["file"], "V5.png")
        self.assertEqual(saved["auth"]["mode"], mc.MODE_A)
        self.assertEqual(res["storage"]["errors"], [])

    def test_map_widget_file_report_and_feedback(self):
        # D19: the widget HTML is written next to result.json, named in the report (no link, no
        # script in the report itself), and reviewer feedback lands under feedback/.
        files = FakeFiles()
        s = storage.Storage(SimpleNamespace(files=files))
        w = runner.RunWriter("suite", self.auth(), {}, s)
        html = "<!doctype html><script>map()</script>"
        case = {"id": "M1", "title": "choropleth: DR-4856 with PW 2", "verdict": "PASS", "serverRunId": "call-x",
                "arguments": {"disaster_number": 4856}, "widget": {"bytes": len(html), "sha256": "abc"}}
        res = w.finish([case], {}, update_latest=False, widgets={"M1": html})
        self.assertEqual(files.data[f"{w.dir}/M1.widget.html"], html.encode())
        saved = json.loads(files.data[f"{w.dir}/result.json"])
        self.assertEqual(saved["cases"][0]["widget"]["file"], "M1.widget.html")
        self.assertNotIn("map()", json.dumps(saved))  # the HTML is in its own file, not in result.json
        page = files.data[f"{w.dir}/report.html"].decode()
        self.assertIn(f"{w.dir}/M1.widget.html", page)
        self.assertNotIn("<script", page.lower())
        self.assertNotRegex(page.lower(), r"<[^>]*\shref\s*=")
        path = runner.save_feedback(s, res, saved["cases"][0], "Works, with problems", "hover box covers dots", "u@x.gov")
        self.assertTrue(path.startswith(f"{w.dir}/feedback/M1-"))
        fb = json.loads(files.data[path])
        self.assertEqual((fb["rating"], fb["comment"], fb["reviewer"], fb["widgetFile"], fb["serverRunId"]),
                         ("Works, with problems", "hover box covers dots", "u@x.gov", "M1.widget.html", "call-x"))
        with self.assertRaises(ValueError):
            runner.save_feedback(s, res, case, "great", "", None)
        broken = storage.Storage(SimpleNamespace(files=FakeFiles(fail=True)))
        self.assertIsNone(runner.save_feedback(broken, res, case, "Does not work", "x", None))

    def test_storage_failure_keeps_results(self):
        s = storage.Storage(SimpleNamespace(files=FakeFiles(fail=True)))
        w = runner.RunWriter("try-it", self.auth(), {}, s)
        cases = sample_cases()
        res = w.finish(cases, {}, update_latest=False)
        self.assertEqual(res["summary"]["PASS"], 1)
        self.assertEqual([c["verdict"] for c in res["cases"]], ["PASS", "FAIL"])
        self.assertGreaterEqual(len(res["storage"]["errors"]), 2)
        self.assertFalse(res["storage"]["resultJsonWritten"])

    def test_final_result_json_failure_leaves_sidecar(self):
        # L11: only result.json fails; the retry also fails, so a sidecar names the errors.
        files = FakeFiles(fail_paths=("/result.json",))
        s = storage.Storage(SimpleNamespace(files=files))
        w = runner.RunWriter("suite", self.auth(), {}, s)
        res = w.finish(sample_cases(), {}, update_latest=False)
        self.assertFalse(res["storage"]["resultJsonWritten"])
        side = json.loads(files.data[f"{w.dir}/result.write-error.json"])
        self.assertEqual(side["clientRunId"], w.client_run_id)
        self.assertEqual(side["summary"]["PASS"], 1)
        self.assertTrue(any(e["path"].endswith("/result.json") for e in side["errors"]))
        self.assertIn(f"{w.dir}/report.html", files.data)

    def test_result_json_written_flag_and_timing_notes(self):
        files = FakeFiles()
        w = runner.RunWriter("try-it", self.auth(), {}, storage.Storage(SimpleNamespace(files=files)))
        res = w.finish(sample_cases(), {}, update_latest=False)
        self.assertTrue(res["storage"]["resultJsonWritten"])
        self.assertNotIn(f"{w.dir}/result.write-error.json", files.data)
        saved = json.loads(files.data[f"{w.dir}/result.json"])
        self.assertEqual(set(saved["timingNotes"]), {"clientMs", "callMs"})


if __name__ == "__main__":
    unittest.main()
