"""Tests for the plain-Python parts of ops/openfema_load.py (BUILD_PLAN D36, D39).

Run: python -m unittest discover -s test -p "test_*.py"   (from the repo root)
No Spark and no network: fetches use a fake `get`.
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

# __file__ is not defined when a Databricks job runs this file as a python task.
_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if not os.path.isdir(os.path.join(_HERE, "..", "ops")):
    _HERE = "/Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-beta/test"
sys.path.insert(0, os.path.join(_HERE, "..", "ops"))
import openfema_load as ol  # noqa: E402

SNAP = dt.date(2026, 11, 6)


def rec(**over):
    base = {
        "disasterNumber": 4611, "declarationDate": "2021-08-29T00:00:00.000Z", "incidentType": "Hurricane",
        "pwNumber": 207, "applicationTitle": "AED Machines", "applicantId": "089-02058-00",
        "damageCategoryCode": "E", "damageCategoryDescrip": "Buildings and Equipment",
        "projectStatus": "Eligible", "projectProcessStep": "Project Closed Out", "projectSize": "Small",
        "county": "St. Charles Parish", "countyCode": "89", "stateAbbreviation": "LA",
        "stateNumberCode": "22", "projectAmount": 4010, "federalShareObligated": 3609,
        "totalObligated": 3609, "lastObligationDate": "2022-04-01T00:00:00.000Z",
        "firstObligationDate": "2022-04-01T00:00:00.000Z", "mitigationAmount": 0, "gmProjectId": 552422,
        "gmApplicantId": 108674, "lastRefresh": "2026-07-24T15:07:02.020Z",
        "hash": "test-fixture-record-hash",  # placeholder; real values look like secrets to scanners
    }
    base.update(over)
    return base


class FakeApi:
    """Serves `rows` in pages like OpenFEMA; `count` overrides the reported count per call."""

    def __init__(self, rows, counts=None, failures=0):
        self.rows, self.counts, self.failures, self.calls = rows, counts, failures, []

    def __call__(self, params):
        self.calls.append(params)
        if self.failures:
            self.failures -= 1
            raise ConnectionError("reset")
        skip, top = params["$skip"], params["$top"]
        count = self.counts[len(self.calls) - 1] if self.counts else len(self.rows)
        return {"metadata": {"count": count}, ol.ENTITY: self.rows[skip:skip + top]}


class Fetch(unittest.TestCase):
    def rows(self, n):
        return [rec(gmProjectId=i, pwNumber=i) for i in range(n)]

    def test_pages_until_short_page(self):
        api = FakeApi(self.rows(25))
        rows, reported = ol.fetch_all(api, dt.date(2021, 1, 1), page_size=10, sleep=lambda s: None)
        self.assertEqual((len(rows), reported, len(api.calls)), (25, 25, 3))
        self.assertEqual([c["$skip"] for c in api.calls], [0, 10, 20])
        self.assertEqual(api.calls[0]["$orderby"], "gmProjectId,hash")
        self.assertEqual(api.calls[0]["$filter"], "declarationDate ge '2021-01-01T00:00:00.000z'")

    def test_exact_multiple_of_page_size_stops(self):
        api = FakeApi(self.rows(20))
        rows, _ = ol.fetch_all(api, dt.date(2021, 1, 1), page_size=10, sleep=lambda s: None)
        self.assertEqual((len(rows), len(api.calls)), (20, 2))

    def test_count_change_fails(self):
        api = FakeApi(self.rows(25), counts=[25, 26, 26])
        with self.assertRaisesRegex(ol.LoadError, "count changed"):
            ol.fetch_all(api, dt.date(2021, 1, 1), page_size=10, sleep=lambda s: None)

    def test_short_fetch_fails(self):
        api = FakeApi(self.rows(25), counts=[30, 30, 30])
        with self.assertRaisesRegex(ol.LoadError, "fetched 25 rows but the source reported 30"):
            ol.fetch_all(api, dt.date(2021, 1, 1), page_size=10, sleep=lambda s: None)

    def test_duplicate_ids_fail(self):
        rows = self.rows(5) + [rec(gmProjectId=0)]
        with self.assertRaisesRegex(ol.LoadError, "duplicate gmProjectId"):
            ol.fetch_all(FakeApi(rows), dt.date(2021, 1, 1), page_size=10, sleep=lambda s: None)

    def test_retries_then_succeeds(self):
        slept = []
        api = FakeApi(self.rows(3), failures=2)
        rows, _ = ol.fetch_all(api, dt.date(2021, 1, 1), page_size=10, sleep=slept.append)
        self.assertEqual((len(rows), slept), (3, [5, 15]))

    def test_gives_up_after_three_attempts(self):
        api = FakeApi(self.rows(3), failures=3)
        with self.assertRaisesRegex(ol.LoadError, "failed after 3 attempts"):
            ol.fetch_all(api, dt.date(2021, 1, 1), page_size=10, sleep=lambda s: None)


class Rows(unittest.TestCase):
    def test_bronze_is_all_strings_in_field_order(self):
        row = ol.bronze_row(rec(projectAmount=1234.5))
        self.assertEqual(len(row), 25)
        self.assertTrue(all(v is None or isinstance(v, str) for v in row))
        self.assertEqual(row[ol.SOURCE_FIELDS.index("projectAmount")], "1234.5")
        self.assertEqual(row[ol.SOURCE_FIELDS.index("countyCode")], "89")

    def test_new_source_field_stops_the_load(self):
        with self.assertRaisesRegex(ol.LoadError, "new fields"):
            ol.bronze_row(rec(surprise=1))

    def test_title_cleaning(self):
        self.assertEqual(ol.clean_title("a\tb\nc\x7fd"), "a b c d")
        self.assertEqual(len(ol.clean_title("x" * 250)), 200)
        self.assertIsNone(ol.clean_title(None))
        self.assertEqual(ol.clean_title("<script>"), "<script>")  # escaping is the widget's job

    def test_geo_county_is_zero_padded(self):
        self.assertEqual(ol.geo_fields("Autauga", "1", "1"), ("01", "01001", "COUNTY", False))
        self.assertEqual(ol.geo_fields("Lee", "12", "71"), ("12", "12071", "COUNTY", False))

    def test_geo_statewide_ignores_its_county_code(self):
        # Statewide rows carry non-zero county codes in the source (checked 2026-11-06)
        self.assertEqual(ol.geo_fields("Statewide", "12", "73"), ("12", None, "STATEWIDE", True))

    def test_geo_unmappable(self):
        for county, code in ((None, "0"), ("Bering Strait School REAA", "0"), ("X", ""), ("X", "12a"), ("X", "1234")):
            self.assertEqual(ol.geo_fields(county, "2", code)[1:], (None, "UNMAPPABLE", False), (county, code))

    def test_silver_row_types_and_whitelist(self):
        row = ol.silver_row(rec(projectAmount=1234.565, applicationTitle="T\x00"), SNAP, "L")
        cols = dict(zip([c for c, _ in ol.SILVER_COLUMNS], row))
        self.assertEqual(len(row), len(ol.SILVER_COLUMNS))
        self.assertEqual(cols["project_amount"], Decimal("1234.57"))
        self.assertEqual(cols["declaration_date"], dt.date(2021, 8, 29))
        self.assertEqual(cols["county_fips"], "22089")
        self.assertEqual(cols["application_title"], "T ")
        self.assertEqual(cols["last_refresh"].tzinfo, dt.timezone.utc)
        for banned in ("hash", "gm_project_id", "gm_applicant_id", "total_obligated", "federal_share_obligated"):
            self.assertNotIn(banned, cols)


class GateAndRetention(unittest.TestCase):
    def test_gate(self):
        self.assertEqual(ol.gate(0, None, 0.5), (False, "0 rows"))
        self.assertEqual(ol.gate(10, None, 0.5)[0], True)        # first load
        self.assertEqual(ol.gate(50, 100, 0.5)[0], True)         # exactly half is allowed
        self.assertEqual(ol.gate(49, 100, 0.5)[0], False)

    def test_retention_is_strict_and_protects_latest(self):
        today = dt.date(2026, 12, 31)
        d = lambda s: dt.date.fromisoformat(s)  # noqa: E731
        dates = [d("2026-09-30"), d("2026-10-01"), d("2026-10-02"), d("2026-12-30")]
        # cutoff = 2026-12-31 - 90 days = 2026-10-02; that day and later are kept
        self.assertEqual(ol.expired_snapshots(dates, today, 90), [d("2026-09-30"), d("2026-10-01")])
        self.assertEqual(ol.expired_snapshots(dates, today, 90, protect=d("2026-09-30")), [d("2026-10-01")])

    def test_args(self):
        a = ol.parse_args([])
        self.assertEqual((a.catalog, a.schema, a.since, a.keep_days, a.min_ratio, a.dry_run),
                         ("users", "tom_jacobson", dt.date(2021, 1, 1), 90, 0.5, False))
        with self.assertRaises(SystemExit):
            ol.parse_args(["--min-ratio", "0"])


def gold(dn, pw, cat="A", amount=100.0, sigma=0.5, **over):
    row = {
        "disaster_number": dn, "pw_number": pw, "applicant_id": f"{pw:03d}-00000-00",
        "application_title": f"Project {pw}", "damage_category_code": cat, "project_status": "Active",
        "project_size": "Large", "state_abbreviation": "FL", "state_fips": "12", "county_fips": "12071",
        "county_name": "Lee", "geo_status": "COUNTY", "project_amount": Decimal(str(amount)),
        "sigma": sigma, "multiple_of_mean": 2.0, "declaration_date": dt.date(2022, 9, 29),
        "incident_type": "Hurricane", "last_refresh": dt.datetime(2026, 7, 24, 15, 7, 2),
    }
    row.update(over)
    return row


class Export(unittest.TestCase):
    def stats(self, dn, cat="A"):
        return {"disaster_number": dn, "damage_category_code": cat, "damage_category_descrip": "Debris Removal",
                "record_count": 2, "mean_amount": 150.0, "stddev_amount": 50.0,
                "total_amount": Decimal("300.00"), "newest_last_refresh": dt.datetime(2026, 7, 24, 15, 7, 2)}

    def test_one_document_per_disaster_sorted(self):
        rows = [gold(4673, 9), gold(4673, 2, sigma=None), gold(4856, 121, state_abbreviation="CA")]
        docs, index = ol.build_exports(rows, [self.stats(4673), self.stats(4856)], "2026-11-06", "L1", "2021-01-01")
        self.assertEqual(sorted(docs), [4673, 4856])
        self.assertEqual([e["disasterNumber"] for e in index], [4673, 4856])
        self.assertEqual([e["projects"] for e in index], [2, 1])
        d = docs[4673]
        self.assertEqual([p["pw"] for p in d["projects"]], [2, 9])
        self.assertIsNone(d["projects"][0]["sigma"])  # stddev 0 stays null, never invented
        self.assertEqual(d["projects"][1]["amount"], 100.0)
        self.assertEqual((d["snapshotDate"], d["loadId"], d["declarationDate"], d["states"]),
                         ("2026-11-06", "L1", "2022-09-29", ["FL"]))
        self.assertEqual(d["newestLastRefresh"], "2026-07-24T15:07:02Z")
        self.assertEqual(d["categories"][0]["recordCount"], 2)
        self.assertEqual(d["categories"][0]["totalAmount"], 300.0)

    def test_documents_carry_no_banned_fields(self):
        docs, _ = ol.build_exports([gold(1, 1)], [self.stats(1)], "2026-11-06", "L", "2021-01-01")
        text = ol.dumps(docs[1])
        for banned in ("hash", "gmProjectId", "gmApplicantId", "Obligated", "coordinates"):
            self.assertNotIn(banned, text)

    def test_dumps_is_ascii_and_rejects_nan(self):
        self.assertEqual(ol.dumps({"t": "La Ca\u00f1ada </script>"}), '{"t":"La Ca\\u00f1ada </script>"}')
        with self.assertRaises(ValueError):
            ol.dumps({"x": float("nan")})

    def test_manifest_add_withdraw_expire(self):
        e1 = {"date": "2026-11-05", "loadId": "a"}
        e2 = {"date": "2026-11-06", "loadId": "b"}
        m1 = ol.build_manifest(None, e1, [], "2021-01-01", "t1")
        self.assertEqual((m1["latest"], len(m1["snapshots"])), ("2026-11-05", 1))
        m2 = ol.build_manifest(m1, e2, [], "2021-01-01", "t2")
        self.assertEqual([s["date"] for s in m2["snapshots"]], ["2026-11-06", "2026-11-05"])
        self.assertEqual(m2["latest"], "2026-11-06")
        withdrawn = ol.build_manifest(m2, None, ["2026-11-06"], "2021-01-01", "t3")  # same-day rerun
        self.assertEqual(withdrawn["latest"], "2026-11-05")
        rerun = ol.build_manifest(withdrawn, dict(e2, loadId="c"), ["2026-11-05"], "2021-01-01", "t4")
        self.assertEqual([(s["date"], s["loadId"]) for s in rerun["snapshots"]], [("2026-11-06", "c")])
        self.assertIsNone(ol.build_manifest(None, None, [], "2021-01-01", "t")["latest"])

    def test_folder_dates_ignore_other_names(self):
        self.assertEqual(ol.folder_dates(["2026-11-06", "tmp", "2026-13-01", "2026-11-06.tmp"]), [dt.date(2026, 11, 6)])

    def test_iso(self):
        self.assertEqual(ol.iso(dt.date(2026, 1, 2)), "2026-01-02")
        self.assertEqual(ol.iso(dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)), "2026-01-02T03:04:05Z")
        self.assertIsNone(ol.iso(None))

    def test_catalog_and_schema_must_be_identifiers(self):
        for bad in (["--catalog", "users`; DROP TABLE x; --"], ["--schema", "tom jacobson"], ["--schema", ""]):
            with self.assertRaises(SystemExit):
                ol.parse_args(bad)
        self.assertEqual(ol.table("users", "tom_jacobson", "load_log"), "`users`.`tom_jacobson`.`openfema_pa_load_log`")
        with self.assertRaises(ValueError):
            ol.table("users", "a`b", "load_log")

    def test_volume_argument(self):
        self.assertEqual(ol.parse_args([]).volume, "/Volumes/users/tom_jacobson/choropleth_data")
        with self.assertRaises(SystemExit):
            ol.parse_args(["--volume", "/tmp/x"])


if __name__ == "__main__":
    _result = unittest.main(exit=False, verbosity=2).result
    if not _result.wasSuccessful():
        raise SystemExit(1)
