"""Tests for ops/trace_cleanup.py selection logic (decision Q7).

Run: python -m unittest discover -s test -p "test_*.py"   (from the repo root)
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
from trace_cleanup import ALLOWED_SUBDIRS, main, select_expired  # noqa: E402

TODAY = dt.date(2026, 12, 15)


class SelectExpired(unittest.TestCase):
    def test_boundary_is_strict(self):
        # cutoff = 2026-11-15; that day and later are kept
        expired, kept, _ = select_expired(["2026-11-14", "2026-11-15", "2026-11-16"], TODAY, 30)
        self.assertEqual(expired, ["2026-11-14"])
        self.assertEqual(kept, ["2026-11-15", "2026-11-16"])

    def test_today_and_future_are_kept(self):
        expired, kept, _ = select_expired(["2026-12-15", "2026-12-16"], TODAY, 30)
        self.assertEqual(expired, [])
        self.assertEqual(kept, ["2026-12-15", "2026-12-16"])

    def test_non_day_names_are_ignored_never_deleted(self):
        names = ["latest", "2026-13-01", "2026-1-1", "backup", "2020-02-30"]
        expired, kept, ignored = select_expired(names, TODAY, 30)
        self.assertEqual(expired, [])
        self.assertEqual(kept, [])
        self.assertEqual(sorted(ignored), sorted(names))

    def test_old_folders_expire(self):
        expired, _, _ = select_expired(["2026-11-04", "2026-11-05", "2025-01-01"], TODAY, 30)
        self.assertEqual(expired, ["2025-01-01", "2026-11-04", "2026-11-05"])

    def test_keep_days_must_be_positive(self):
        with self.assertRaises(ValueError):
            select_expired(["2026-11-04"], TODAY, 0)

    def test_refuses_non_volume_path(self):
        with self.assertRaises(SystemExit):
            main(["--volume", "/Workspace/Users/someone", "--dry-run"])

    def test_only_runs_and_client_runs_are_cleanable(self):
        self.assertEqual(ALLOWED_SUBDIRS, ("runs", "client-runs"))
        for bad in ("latest", "..", "client-runs/latest", ""):
            with self.assertRaises(SystemExit):
                main(["--subdir", bad, "--dry-run"])

    def test_client_runs_latest_is_never_a_day_folder(self):
        expired, kept, ignored = select_expired(["latest", "2000-01-01"], TODAY, 30)
        self.assertEqual(expired, ["2000-01-01"])
        self.assertEqual(ignored, ["latest"])


if __name__ == "__main__":
    unittest.main()
