"""Tests for ops/declarations_load.py (BUILD_PLAN D44).

Run: python -m unittest discover -s test -p "test_*.py"   (from the repo root)
No network: declaration zips are built byte by byte (helpers from test_county_boundaries_load);
OpenFEMA and gis.fema.gov use fakes; files go to a temp folder.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if not os.path.isdir(os.path.join(_HERE, "..", "ops")):
    _HERE = "/Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-beta/test"
sys.path.insert(0, os.path.join(_HERE, "..", "ops"))
sys.path.insert(0, _HERE)
import declarations_load as dl  # noqa: E402
from test_county_boundaries_load import NAD83, cw_square, make_dbf, make_shp  # noqa: E402


def dec_zip(rows, upper=False, member="dec_9999_amd3"):
    """rows: [(fips, name, designate, rings)] -> a FEMA-style dec_<n>.zip."""
    names = ["FIPS", "NAME", "DESIGNATE", "CURR_AMD"] if upper else ["fips", "name", "designate", "curr_amd"]
    fields = [(names[0], "C", 5), (names[1], "C", 40), (names[2], "C", 12), (names[3], "C", 4)]
    recs = [{names[0]: f, names[1]: n, names[2]: d, names[3]: "3"} for f, n, d, _ in rows]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{member}.shp", make_shp([r for *_, r in rows]))
        zf.writestr(f"{member}.dbf", make_dbf(fields, recs))
        zf.writestr(f"{member}.prj", NAD83)
    return buf.getvalue()


SQ = [cw_square(0, 0)]


class Rule(unittest.TestCase):
    def test_affected_rule(self):
        cases = {"IAPAA-G": True, "PAA-G": True, "IAPAB": True, "IAPAAB": True, "PAAB": True, "PAA": True,
                 "PAC-G": True, "IA": True, "IAPA": True, "PA": True, "PAB": False, "": False, None: False,
                 " paa-g ": True}
        for code, want in cases.items():
            self.assertEqual(dl.parse_designation(code)["affected"], want, code)

    def test_categories_and_unrecognized(self):
        self.assertEqual(dl.parse_designation("PAA-C")["categories"], ["A", "B", "C"])
        self.assertEqual(dl.parse_designation("PAAB")["categories"], ["A", "B"])
        d = dl.parse_designation("HM")
        self.assertFalse(d["recognized"])
        self.assertFalse(d["affected"])
        self.assertTrue(dl.parse_designation("IAXYZ")["affected"])   # unknown shape, IA still counts

    def test_title(self):
        self.assertEqual(dl.format_title("DR", 4856, "CA", "WILDFIRES AND STRAIGHT-LINE WINDS"),
                         "DR-4856-CA Wildfires and Straight-line Winds")
        self.assertEqual(dl.format_title("EM", 3553, "DC", "59TH PRESIDENTIAL INAUGURATION"),
                         "EM-3553-DC 59th Presidential Inauguration")
        self.assertEqual(dl.format_title("DR", 4611, "LA", "HURRICANE IDA"), "DR-4611-LA Hurricane Ida")
        self.assertEqual(dl.format_title("DR", 1, "XX", "THE STORM OF THE CENTURY"), "DR-1-XX The Storm of the Century")
        self.assertEqual(dl.format_title(None, 7, "XX", ""), "DR-7-XX")


class Parse(unittest.TestCase):
    def doc(self, data):
        return dl.declaration_doc(9999, {"shapefileUrl": "u", "hash": "h"},
                                  {"state": "XX", "declarationTitle": "HURRICANE TEST", "declarationType": "DR"},
                                  data, "L", "T")

    def test_lower_and_upper_field_names(self):
        rows = [("12001", "Alachua", "IAPAA-G", SQ), ("12003", "Baker", "PAB", SQ), ("12005", "Bay", "", SQ),
                ("12007", "Bradford", "PAA-G", SQ)]
        for upper in (False, True):
            d = self.doc(dec_zip(rows, upper=upper))
            self.assertEqual(d["status"], dl.OK)
            self.assertEqual(d["affectedFips"], ["12001", "12007"])
            self.assertEqual(len(d["counties"]), 4)
            self.assertEqual(d["stateFips"], "12")
            self.assertEqual(d["title"], "DR-9999-XX Hurricane Test")
            self.assertEqual(d["currentAmendment"], "3")
            self.assertEqual(d["designationCodes"], {"": 1, "IAPAA-G": 1, "PAA-G": 1, "PAB": 1})

    def test_tribal_rows_without_fips(self):
        rows = [("12001", "Alachua", "IAPAA-G", SQ), ("", "Seminole Tribe", "PAB", SQ),
                ("", "Miccosukee Tribe", "IAPAA-G", [cw_square(5, 5)])]
        d = self.doc(dec_zip(rows))
        self.assertEqual(d["affectedFips"], ["12001"])
        self.assertEqual([e["name"] for e in d["extraAreas"]], ["Miccosukee Tribe"])   # PAB-only tribe is not drawn
        self.assertEqual(len(d["extraAreas"][0]["polygons"]), 1)

    def test_tribal_only_declaration_gets_state_from_code(self):
        d = dl.declaration_doc(4582, {"shapefileUrl": "u", "hash": "h"},
                               {"state": "AZ", "declarationTitle": "COVID-19 PANDEMIC", "declarationType": "DR"},
                               dec_zip([("", "Navajo Nation", "PAA-G", SQ)]), "L", "T")
        self.assertEqual((d["stateFips"], d["affectedFips"], len(d["extraAreas"])), ("04", [], 1))
        self.assertEqual(d["title"], "DR-4582-AZ Covid-19 Pandemic")

    def test_duplicate_fips_rows_merge(self):
        d = self.doc(dec_zip([("22001", "Acadia", "PAB", SQ), ("22001", "Acadia", "IAPAA-G", SQ)]))
        self.assertEqual(d["affectedFips"], ["22001"])
        self.assertEqual(d["counties"][0]["designate"], "IAPAA-G")

    def test_multi_amendment_zip_uses_highest(self):
        old = dec_zip([("12001", "Alachua", "PAB", SQ)], member="dec_9999")
        amd2 = dec_zip([("12001", "Alachua", "IAPAA-G", SQ)], member="dec_9999_amd2")
        amd10 = dec_zip([("12001", "Alachua", "IAPAA-G", SQ), ("12003", "Baker", "PAA", SQ)], member="dec_9999_amd10")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as out:
            for data in (old, amd2, amd10):
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for n in zf.namelist():
                        out.writestr(n, zf.read(n))
            out.writestr("dec_9999.lyrx", "{}")
            out.writestr("dec_9999_amd10.shp.xml", "<x/>")
        d = self.doc(buf.getvalue())
        self.assertEqual(d["source"]["shapefileUsed"], "dec_9999_amd10")   # 10 > 2 (numeric, not text)
        self.assertEqual(d["source"]["shapefilesInZip"], 3)
        self.assertEqual(d["affectedFips"], ["12001", "12003"])

    def test_bad_zip_is_parse_failed(self):
        d = self.doc(b"not a zip")
        self.assertEqual(d["status"], dl.PARSE_FAILED)
        self.assertEqual(d["title"], "DR-9999-XX Hurricane Test")   # the title still reaches the fallback image

    def test_failure_share(self):
        ok = [{"disasterNumber": i, "status": dl.OK} for i in range(9)]
        dl.check_failures(ok + [{"disasterNumber": 9, "status": dl.FETCH_FAILED}])      # 10% passes
        with self.assertRaises(dl.LoadError):
            dl.check_failures(ok[:8] + [{"disasterNumber": 8, "status": dl.PARSE_FAILED}] * 2)


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vol = self.tmp.name
        os.makedirs(f"{self.vol}/snapshots/2026-11-12")
        with open(f"{self.vol}/manifest.json", "w") as fh:
            json.dump({"schemaVersion": 1, "latest": "2026-11-12", "declarationsSince": "2021-01-01"}, fh)
        with open(f"{self.vol}/snapshots/2026-11-12/index.json", "w") as fh:
            json.dump({"disasters": [{"disasterNumber": 4001}, {"disasterNumber": 4002}, {"disasterNumber": 4003}]}, fh)
        self.web = {4001: {"disasterNumber": 4001, "shapefileUrl": "https://gis.fema.gov/maps/dec_4001.zip", "hash": "a", "stateCode": "FL"},
                    4002: {"disasterNumber": 4002, "shapefileUrl": None, "hash": "b", "stateCode": "LA"}}
        self.downloads = []

    def tearDown(self):
        self.tmp.cleanup()

    def get_json(self, url, params):
        if url == dl.FEMA_WEB_URL:
            return {"FemaWebDisasterDeclarations": list(self.web.values()) if params["$skip"] == 0 else []}
        rows = [{"disasterNumber": 4001, "declarationTitle": "HURRICANE A", "declarationType": "DR", "state": "FL"},
                {"disasterNumber": 4001, "declarationTitle": "HURRICANE A", "declarationType": "DR", "state": "FL"},
                {"disasterNumber": 4002, "declarationTitle": "FLOODING", "declarationType": "DR", "state": "LA"}]
        return {"DisasterDeclarationsSummaries": rows if params["$skip"] == 0 else []}

    def get_bytes(self, url):
        self.downloads.append(url)
        return dec_zip([("12001", "Alachua", "IAPAA-G", SQ), ("12003", "Baker", "PAB", SQ)])

    def run_once(self, **kw):
        return dl.run(self.vol, get_json=self.get_json, get_bytes=self.get_bytes, sleep=lambda s: None, **kw)

    def read(self, rel):
        with open(f"{self.vol}/declarations/v1/{rel}") as fh:
            return json.load(fh)

    def test_writes_files_then_manifest(self):
        s = self.run_once()
        self.assertEqual(s["statuses"], {dl.OK: 1, dl.NO_URL: 1, dl.NO_RECORD: 1})
        d = self.read("disasters/4001.json")
        self.assertEqual((d["title"], d["affectedFips"]), ("DR-4001-FL Hurricane A", ["12001"]))
        self.assertEqual(self.read("disasters/4002.json")["title"], "DR-4002-LA Flooding")
        m = self.read("manifest.json")
        self.assertEqual([e["disasterNumber"] for e in m["disasters"]], [4001, 4002, 4003])
        self.assertEqual(m["downloads"], 1)
        self.assertFalse(os.path.exists(f"{self.vol}/declarations/v1/disasters/4001.json.tmp"))

    def test_unchanged_record_is_reused(self):
        self.run_once()
        s = self.run_once()
        self.assertEqual((s["downloads"], s["reused"]), (0, 1))
        self.web[4001]["hash"] = "changed"
        s = self.run_once()
        self.assertEqual((s["downloads"], s["reused"]), (1, 0))
        s = self.run_once(force=True)
        self.assertEqual(s["downloads"], 1)

    def test_only_keeps_other_entries(self):
        self.run_once()
        self.run_once(only=[4002])
        self.assertEqual([e["disasterNumber"] for e in self.read("manifest.json")["disasters"]], [4001, 4002, 4003])

    def test_missing_export_manifest_fails(self):
        os.remove(f"{self.vol}/manifest.json")
        with self.assertRaises(dl.LoadError):
            self.run_once()


if __name__ == "__main__":
    unittest.main()
