"""Smoke tests for app.py with Streamlit's AppTest (code review L10). No network: auth and
the server calls are replaced. Skipped when streamlit is not installed."""

import os
import unittest

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

from client import mcp_client as mc

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._saved = (mc.resolve_auth, mc.reuse_auth)

        def fake_resolve(headers, probe=None, force_mode_b=False):
            self.calls.append(force_mode_b)
            if force_mode_b:
                return mc.Auth(mc.MODE_B, "t", None, "sp-id", "forced"), {"forcedModeB": True}
            return mc.Auth(mc.MODE_A, "t", "u@x.gov", None, "ok"), {"forcedModeB": False}

        def fake_reuse(headers, decision):
            m = decision.get("mode")
            return mc.Auth(m, "t", "u@x.gov" if m == mc.MODE_A else None, None, decision.get("note") or "")

        mc.resolve_auth, mc.reuse_auth = fake_resolve, fake_reuse

    def tearDown(self):
        mc.resolve_auth, mc.reuse_auth = self._saved

    def test_pages_render_and_auth_is_cached(self):
        at = AppTest.from_file(APP, default_timeout=60).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(self.calls, [False])
        # L2: a plain rerun reuses the decision instead of probing again
        at.run()
        self.assertEqual(self.calls, [False])
        # switching to Mode B re-resolves
        at.toggle[0].set_value(True).run()
        self.assertEqual(self.calls, [False, True])
        self.assertTrue(any("Auth mode B" in w.value for w in at.warning))
        self.assertEqual(at.sidebar.radio[0].options, ["Test suite", "Try It - Mermaid", "Try It - FEMA", "Connection"])
        for page in ("Try It - Mermaid", "Try It - FEMA", "Connection"):
            at.sidebar.radio[0].set_value(page).run()
            self.assertFalse(at.exception, (page, [e.value for e in at.exception]))
        # the Connection page's Re-check button always resolves again
        n = len(self.calls)
        next(b for b in at.button if b.label == "Re-check auth now").click().run()
        self.assertEqual(len(self.calls), n + 1)

    def test_suite_page_shows_map_widget_and_saves_feedback(self):
        # D19: map widgets are shown inline after a run, each with a feedback form.
        from client import report, runner

        saved = []
        orig = runner.save_feedback
        runner.save_feedback = lambda store, res, case, rating, comment, reviewer: (
            saved.append((case["id"], rating, comment, reviewer)) or "/Volumes/x/feedback/M1-1.json")
        try:
            case = {"id": "M1", "title": "choropleth: DR-4856 with PW 2", "verdict": "PASS", "actual": "ok",
                    "clientMs": 1, "serverRunId": "call-x", "widget": {"bytes": 10, "sha256": "abc", "file": "M1.widget.html"}}
            res = report.build_result(client_run_id="client-x", kind="suite", started_at="a", finished_at="b",
                                      auth={"mode": mc.MODE_A, "callerEmail": "u@x.gov"}, auth_finding={},
                                      cases=[case], versions={}, storage_errors=[], run_dir="/Volumes/x",
                                      server_base="https://s")
            at = AppTest.from_file(APP, default_timeout=60)
            at.session_state["last_suite"] = (res, {}, {"M1": "<!doctype html><p>map</p>"})
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertTrue(any("Interactive maps" in h.value for h in at.subheader))
            rating = next(r for r in at.radio if r.label == "How did it work?")
            rating.set_value("Works, with problems")
            next(t for t in at.text_area if t.label.startswith("Comments")).input("legend overlaps")
            next(b for b in at.button if b.label == "Save feedback on M1").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertEqual(saved, [("M1", "Works, with problems", "legend overlaps", "u@x.gov")])
            self.assertTrue(any("Saved: /Volumes/x/feedback/M1-1.json" in s.value for s in at.success))
        finally:
            runner.save_feedback = orig

    def test_try_fema_page_sends_form_args_and_shows_map(self):
        # D20: one generate_choropleth call from the page, map inline, history and feedback.
        from client import report, runner, suite

        sent, saved = [], []
        orig = (runner.try_fema, runner.save_feedback)

        def fake_try(auth, finding, store, args):
            sent.append(args)
            n = len(sent)
            ok = args.get("disaster_number") != 1
            rec = {"id": "TRY", "title": "try-it generate_choropleth", "verdict": suite.PASS if ok else suite.INFO,
                   "actual": "ok" if ok else "DISASTER_NOT_LOADED", "arguments": args, "mcpIsError": not ok,
                   "errorCode": None if ok else "DISASTER_NOT_LOADED", "stage": None if ok else "data",
                   "widget": {"bytes": 9, "sha256": "abc", "file": "TRY.widget.html", "csp": True, "externalUrls": []} if ok else None}
            res = report.build_result(client_run_id=f"client-try-{n}", kind="try-fema", started_at="a", finished_at="b",
                                      auth={"mode": mc.MODE_A, "callerEmail": "u@x.gov"}, auth_finding={}, cases=[rec],
                                      versions={}, storage_errors=[], run_dir=f"/Volumes/x/{n}", server_base="https://s")
            return {"res": res, "rec": rec, "html": "<p>map</p>" if ok else None, "texts": ["DR summary"] if ok else [],
                    "structured": {"status": "OK"} if ok else None,
                    "meta": None if ok else {"message": "disaster 1 is not in the snapshot"}}

        runner.try_fema = fake_try
        runner.save_feedback = lambda store, res, case, rating, comment, reviewer: (
            saved.append((res["clientRunId"], case["id"], rating)) or "/Volumes/x/fb.json")
        try:
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.sidebar.radio[0].set_value("Try It - FEMA").run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            # the first preset, PW 2, sigma sent as a number
            next(t for t in at.text_input if t.label.startswith("pw_number")).input("2")
            next(c for c in at.checkbox if c.label == "Send sigma_threshold").check()
            at.run()
            next(s for s in at.slider if s.label == "sigma_threshold").set_value(4.5)
            next(b for b in at.button if b.label == "Generate map").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            # D50: map_aspect_ratio 16:9 is sent by default, with every preset
            self.assertEqual(sent[-1], {"disaster_number": 4856, "pw_number": 2, "sigma_threshold": 4.5, "map_aspect_ratio": "16:9"})
            self.assertEqual(next(s for s in at.selectbox if s.label == "map_aspect_ratio").options,
                             ["(not sent: server default)", "1:1", "16:9", "4:3", "5:3", "9:16", "3:4", "3:5"])
            self.assertTrue(any("DR summary" in i.value for i in at.info))
            self.assertTrue(any("Feedback on this map" in h.value for h in at.subheader))
            next(r for r in at.radio if r.label == "How did it work?").set_value("Works as expected")
            next(b for b in at.button if b.label == "Save feedback").click().run()
            self.assertEqual(saved, [("client-try-1", "TRY", "Works as expected")])
            # numbers as strings, then a raw-JSON edit that sends a disaster that is not loaded
            next(c for c in at.checkbox if c.label == "Send numbers as strings").check()
            at.run()
            next(b for b in at.button if b.label == "Generate map").click().run()
            self.assertEqual(sent[-1], {"disaster_number": "4856", "pw_number": "2", "sigma_threshold": "4.5", "map_aspect_ratio": "16:9"})
            # D46 display options: the FEMA Pulse preset sends all six (booleans as strings here)
            next(r for r in at.radio if r.label == "Display preset").set_value("FEMA Pulse").run()
            next(b for b in at.button if b.label == "Generate map").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertEqual(sent[-1], {"disaster_number": "4856", "pw_number": "2", "sigma_threshold": "4.5",
                                        "initial_view": "all", "show_pause_button": "false", "show_pw_card": "false",
                                        "show_all_categories_card": "false", "legend_position": "below_map",
                                        "click_details": "modal", "map_aspect_ratio": "16:9"})
            next(c for c in at.checkbox if c.label == "Send numbers as strings").uncheck()
            next(r for r in at.radio if r.label == "Display preset").set_value("Custom").run()
            next(s for s in at.selectbox if s.label == "click_details").set_value("modal").run()
            next(s for s in at.selectbox if s.label == "show_pause_button").set_value(False).run()
            next(s for s in at.selectbox if s.label == "map_aspect_ratio").set_value("9:16").run()
            next(b for b in at.button if b.label == "Generate map").click().run()
            self.assertEqual(sent[-1], {"disaster_number": 4856, "pw_number": 2, "sigma_threshold": 4.5,
                                        "show_pause_button": False, "click_details": "modal", "map_aspect_ratio": "9:16"})
            next(r for r in at.radio if r.label == "Display preset").set_value("Server defaults").run()
            next(s for s in at.selectbox if s.label == "map_aspect_ratio").set_value("(not sent: server default)").run()
            next(b for b in at.button if b.label == "Generate map").click().run()
            self.assertEqual(sent[-1], {"disaster_number": 4856, "pw_number": 2, "sigma_threshold": 4.5})
            next(c for c in at.checkbox if c.label == "Send numbers as strings").check()
            at.run()
            next(t for t in at.text_area if t.label == "JSON object").input('{"disaster_number": 1}')
            next(b for b in at.button if b.label == "Generate map").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertEqual(sent[-1], {"disaster_number": 1})
            self.assertTrue(any("disaster 1 is not in the snapshot" in w.value for w in at.warning))
            self.assertEqual(len(next(s for s in at.selectbox if s.label == "Show try").options), 6)  # history
        finally:
            runner.try_fema, runner.save_feedback = orig

    def test_paste_text_has_a_limit(self):
        at = AppTest.from_file(APP, default_timeout=60).run()
        at.sidebar.radio[0].set_value("Try It - Mermaid").run()
        at.radio[0].set_value("Paste text").run()
        self.assertEqual(at.text_area[0].max_chars, 4_000_000)


if __name__ == "__main__":
    unittest.main()
