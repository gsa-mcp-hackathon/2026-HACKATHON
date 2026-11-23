"""Tests for the plain-Python parts of ops/county_boundaries_load.py (BUILD_PLAN D43).

Run: python -m unittest discover -s test -p "test_*.py"   (from the repo root)
No Spark and no network: shapefiles are built here byte by byte; fetches use a fake opener.
"""
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if not os.path.isdir(os.path.join(_HERE, "..", "ops")):
    _HERE = "/Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-beta/test"
sys.path.insert(0, os.path.join(_HERE, "..", "ops"))
import county_boundaries_load as cb  # noqa: E402

NAD83 = 'GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'


def cw_square(x, y, s=1.0):
    """Shapefile outer ring: clockwise, closed."""
    return [(x, y), (x, y + s), (x + s, y + s), (x + s, y), (x, y)]


def ccw_square(x, y, s=1.0):
    return list(reversed(cw_square(x, y, s)))


def make_shp(shapes):
    recs = []
    for i, rings in enumerate(shapes, 1):
        if rings is None:
            content = struct.pack("<i", 0)
        else:
            pts = [p for r in rings for p in r]
            parts, n = [], 0
            for r in rings:
                parts.append(n)
                n += len(r)
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            content = struct.pack("<i4d2i", 5, min(xs), min(ys), max(xs), max(ys), len(rings), len(pts))
            content += struct.pack(f"<{len(parts)}i", *parts) + struct.pack(f"<{2 * len(pts)}d", *[c for p in pts for c in p])
        recs.append(struct.pack(">ii", i, len(content) // 2) + content)
    body = b"".join(recs)
    header = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (100 + len(body)) // 2) + struct.pack("<2i8d", 1000, 5, 0, 0, 0, 0, 0, 0, 0, 0)
    return header + body


def make_dbf(fields, rows, deleted=()):
    """fields: [(name, type, width)]; rows: list of dicts."""
    record_len = 1 + sum(w for _, _, w in fields)
    header_len = 32 + 32 * len(fields) + 1
    out = bytearray(struct.pack("<BBBBIHH20x", 3, 126, 11, 6, len(rows), header_len, record_len))
    for name, kind, width in fields:
        out += name.encode("ascii").ljust(11, b"\x00") + kind.encode("ascii") + b"\x00" * 4 + bytes([width, 0]) + b"\x00" * 14
    out += b"\x0d"
    for i, row in enumerate(rows):
        out += b"*" if i in deleted else b" "
        for name, kind, width in fields:
            val = str(row.get(name, "")).encode("utf-8")
            out += (val.rjust(width) if kind == "N" else val.ljust(width))[:width]
    out += b"\x1a"
    return bytes(out)


FIELDS = [("STATEFP", "C", 2), ("COUNTYFP", "C", 3), ("GEOID", "C", 5), ("NAME", "C", 40), ("NAMELSAD", "C", 60),
          ("STUSPS", "C", 2), ("LSAD", "C", 2), ("ALAND", "N", 14), ("AWATER", "N", 14)]


def attrs(geoid, name, stusps="XX"):
    return {"STATEFP": geoid[:2], "COUNTYFP": geoid[2:], "GEOID": geoid, "NAME": name, "NAMELSAD": f"{name} County",
            "STUSPS": stusps, "LSAD": "06", "ALAND": 1000, "AWATER": 10}


def make_zip(records, prj=NAD83, cpg="UTF-8", extra=None, deleted=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cb.shp", make_shp([r for _, r in records]))
        zf.writestr("cb.dbf", make_dbf(FIELDS, [a for a, _ in records], deleted))
        zf.writestr("cb.prj", prj)
        if cpg:
            zf.writestr("cb.cpg", cpg)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def feature(geoid, polygons, vintage=2025, name=None):
    return {"vintage": vintage, "scale": "5m", "geoid": geoid, "statefp": geoid[:2], "countyfp": geoid[2:], "stusps": "XX",
            "name": name or geoid, "namelsad": f"{name or geoid} County", "lsad": "06", "aland": 1, "awater": 0, "polygons": polygons}


def sq(x, y, s=1.0):
    """RFC 7946 polygon list for one square."""
    return [[ccw_square(x, y, s)]]


class Readers(unittest.TestCase):
    def test_zip_roundtrip_with_utf8_names_hole_and_deleted_record(self):
        recs = [(attrs("72011", "Añasco", "PR"), [cw_square(0, 0, 4), ccw_square(1, 1, 1)]),
                (attrs("72013", "Gone", "PR"), [cw_square(9, 9)]),
                (attrs("72015", "Arroyo", "PR"), [cw_square(4, 0), cw_square(10, 0)])]
        parsed = cb.read_zip(make_zip(recs, deleted={1}))
        self.assertEqual([a["GEOID"] for a, _ in parsed["records"]], ["72011", "72015"])
        self.assertEqual(parsed["records"][0][0]["NAME"], "Añasco")
        self.assertEqual(parsed["records"][0][0]["ALAND"], 1000)
        feats, errors = cb.build_features(parsed, 2025, "5m")
        self.assertEqual(errors, [])
        a, b = feats
        self.assertEqual(len(a["polygons"]), 1)
        self.assertEqual(len(a["polygons"][0]), 2, "hole attached to its outer ring")
        self.assertGreater(cb.ring_area(a["polygons"][0][0]), 0, "outer ring counter-clockwise")
        self.assertLess(cb.ring_area(a["polygons"][0][1]), 0, "hole clockwise")
        self.assertAlmostEqual(cb.polygons_area(a["polygons"]), 15.0)
        self.assertEqual(len(b["polygons"]), 2, "two separate pieces")

    def test_zip_must_hold_one_of_each_and_counts_must_agree(self):
        recs = [(attrs("06037", "Los Angeles"), [cw_square(0, 0)])]
        with self.assertRaises(cb.LoadError):
            cb.read_zip(make_zip(recs, extra={"other.shp": b"x"}))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("cb.shp", make_shp([cw_square(0, 0)] * 2 and [[cw_square(0, 0)], [cw_square(1, 1)]]))
            zf.writestr("cb.dbf", make_dbf(FIELDS, [attrs("06037", "Los Angeles")]))
            zf.writestr("cb.prj", NAD83)
        with self.assertRaises(cb.LoadError):
            cb.read_zip(buf.getvalue())
        with self.assertRaises(cb.LoadError):
            cb.read_shp(b"\x00" * 100)

    def test_bad_geoids_and_empty_geometry_are_errors(self):
        recs = [(attrs("06037", "A"), [cw_square(0, 0)]), ({**attrs("06037", "Dup")}, [cw_square(1, 0)]),
                ({**attrs("06111", "B"), "GEOID": "06999"}, [cw_square(2, 0)]), (attrs("06113", "Empty"), None)]
        feats, errors = cb.build_features(cb.read_zip(make_zip(recs)), 2025, "5m")
        self.assertEqual([f["geoid"] for f in feats], ["06037"])
        self.assertEqual(len(errors), 3)

    def test_projection_check(self):
        self.assertTrue(cb.prj_is_nad83_geographic(NAD83))
        self.assertFalse(cb.prj_is_nad83_geographic('PROJCS["NAD83 / Albers",GEOGCS["NAD83"]]'))
        self.assertFalse(cb.prj_is_nad83_geographic('GEOGCS["WGS 84"]'))


class Geometry(unittest.TestCase):
    def test_rounding_keeps_shared_vertices_and_drops_collapsed_rings(self):
        a = cb.round_polygons([[[(0.0, 0.0), (1.0000004, 0.0), (1.0000004, 1.0), (0.0, 1.0), (0.0, 0.0)]]])
        b = cb.round_polygons([[[(1.0000004, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0000004, 1.0), (1.0000004, 0.0)]]])
        self.assertIn((1.0, 0.0), a[0][0])
        self.assertIn((1.0, 0.0), b[0][0])
        self.assertEqual(cb.round_polygons([[[(0.0, 0.0), (0.000001, 0.0), (0.0, 0.000001), (0.0, 0.0)]]]), [])

    def test_adjacency_needs_a_shared_edge_not_a_corner(self):
        feats = [feature(f"1200{i}", sq(i % 3, i // 3)) for i in range(9)]
        adj = cb.adjacency(feats)
        self.assertEqual(sorted(adj["12004"]), ["12001", "12003", "12005", "12007"])
        self.assertEqual(sorted(adj["12000"]), ["12001", "12003"])

    def test_dissolve_cancels_shared_edges(self):
        merged = cb.dissolve([sq(0, 0), sq(1, 0)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]), 1)
        self.assertAlmostEqual(cb.polygons_area(merged), 2.0)
        self.assertEqual(len(merged[0][0]), 7, "6 corners + closing point; the shared edge is gone")
        ring = cb.dissolve([sq(0, 0), sq(1, 0), sq(2, 0), sq(0, 1), sq(2, 1), sq(0, 2), sq(1, 2), sq(2, 2)])
        self.assertEqual([len(p) for p in ring], [2], "a ring of 8 squares leaves a hole in the middle")
        self.assertAlmostEqual(cb.polygons_area(ring), 8.0)
        apart = cb.dissolve([sq(0, 0), sq(5, 5)])
        self.assertEqual(len(apart), 2)


class Composition(unittest.TestCase):
    def setUp(self):
        # state 09: two planning regions (2025) vs. three legacy counties (2021) over the same 2x1 area
        self.primary = [feature("09110", sq(0, 0)), feature("09120", sq(1, 0)),
                        feature("02063", [[cb.round_polygons(sq(10, 0))[0][0]], [ccw_square(20, 20)]]), feature("02066", sq(11, 0)),
                        feature("02090", sq(10, 1)), feature("06037", sq(30, 0)), feature("06059", sq(31, 0))]
        self.legacy = {"09": [feature("09001", [[ccw_square(0, 0, 0.5)]], 2021), feature("09003", [[[(0.5, 0), (2, 0), (2, 1), (0, 1), (0, 0.5), (0.5, 0.5), (0.5, 0)]]], 2021)]}

    def test_compose_rules_and_crosswalk(self):
        states, rules, notes = cb.compose_states(self.primary, self.legacy)
        self.assertEqual([f["geoid"] for f in states["09"]], ["09001", "09003"])
        self.assertEqual([f["geoid"] for f in states["02"]], ["02090", "02261"])
        self.assertEqual(rules["02261"], ("DISSOLVE", 2025, ["02063", "02066"]))
        self.assertEqual(rules["09001"], ("LEGACY_VINTAGE", 2021, ["09001"]))
        self.assertNotIn("09110", rules)
        ak = states["02"][1]
        self.assertEqual((ak["name"], ak["namelsad"]), ("Valdez-Cordova", "Valdez-Cordova Census Area"))
        self.assertEqual(len(ak["polygons"]), 2, "mainland merged; the island stays separate")
        states["02"].append(feature("02105", sq(12, 0)))
        rules["02105"] = ("IDENTITY", 2025, ["02105"])
        fema = [{"county_fips": c, "county_name": c, "state_fips": c[:2], "projects": 1, "disasters": 1} for c in ("09001", "02261", "06037", "09110", "02232")]
        cross = cb.crosswalk(fema, states, rules)
        self.assertEqual({r["county_fips"]: r["rule"] for r in cross},
                         {"02232": "RECODE", "02261": "DISSOLVE", "06037": "IDENTITY", "09001": "LEGACY_VINTAGE", "09110": "UNMATCHED"})
        self.assertEqual(next(r for r in cross if r["county_fips"] == "02232")["shape_geoid"], "02105")
        self.assertEqual(cb.state_file("02", states["02"], "s", "L")["aliases"], {"02232": "02105"})
        self.assertEqual(cb.state_file("06", states["06"], "s", "L")["aliases"], {})
        self.assertIn("02063 + 02066", cb.source_text(states["02"], rules, "5m"))
        self.assertIn("2021", cb.source_text(states["09"], rules, "5m"))

    def test_checks(self):
        states, rules, _ = cb.compose_states(self.primary, self.legacy)
        fema_ok = [{"county_fips": "06037", "county_name": "Los Angeles County", "state_fips": "06", "projects": 3, "disasters": 1}]
        sources = [{"file": "cb_2025_us_county_5m.zip", "prj": NAD83}]
        checks, lonely = cb.run_checks(sources, self.primary, [], self.legacy, [], states, rules, cb.crosswalk(fema_ok, states, rules))
        by = {c["name"]: c for c in checks}
        self.assertFalse(by["primary:count"]["ok"], "7 features is far below the national range")
        for name in ("projection:cb_2025_us_county_5m.zip", "legacy:area:09", "dissolve:02261", "adjacency:shared-vertices", "crosswalk:coverage"):
            self.assertTrue(by[name]["ok"], (name, by[name]["detail"]))
        bad_fema = fema_ok + [{"county_fips": "09110", "county_name": "Capitol Planning Region", "state_fips": "09", "projects": 1, "disasters": 1}]
        checks, _ = cb.run_checks(sources, self.primary, [], self.legacy, [], states, rules, cb.crosswalk(bad_fema, states, rules))
        self.assertEqual({c["name"]: c["ok"] for c in checks}["crosswalk:coverage"], False)
        # a county whose only neighbor is in another state still has a neighbor
        cross_state = dict(states, **{"44": [feature("44001", sq(70, 0)), feature("44005", sq(80, 0))],
                                      "25": [feature("25005", sq(81, 0)), feature("25001", sq(71, 0))]})
        checks, lonely = cb.run_checks(sources, self.primary, [], self.legacy, [], cross_state, rules, [])
        self.assertTrue({c["name"]: c["ok"] for c in checks}["adjacency:shared-vertices"])
        self.assertNotIn("44", lonely)
        # a non-island state whose counties do not touch fails the shared-vertex check
        apart = dict(states, **{"06": [feature("06037", sq(30, 0)), feature("06059", sq(40, 0))]})
        checks, lonely = cb.run_checks(sources, self.primary, [], self.legacy, [], apart, rules, [])
        self.assertFalse({c["name"]: c["ok"] for c in checks}["adjacency:shared-vertices"])
        self.assertEqual(lonely["06"], ["06037", "06059"])
        # island territories may have no neighbors
        islands = dict(states, **{"78": [feature("78010", sq(50, 0)), feature("78020", sq(60, 0))]})
        checks, _ = cb.run_checks(sources, self.primary, [], self.legacy, [], islands, rules, [])
        self.assertTrue({c["name"]: c["ok"] for c in checks}["adjacency:shared-vertices"])
        # legacy area that does not match the primary state fails
        shrunk = {"09": [feature("09001", [[ccw_square(0, 0, 0.5)]], 2021)]}
        st2, r2, _ = cb.compose_states(self.primary, shrunk)
        checks, _ = cb.run_checks(sources, self.primary, [], shrunk, [], st2, r2, [])
        self.assertFalse({c["name"]: c["ok"] for c in checks}["legacy:area:09"])

    def test_missing_dissolve_parts_fail(self):
        with self.assertRaises(cb.LoadError):
            cb.compose_states([f for f in self.primary if f["geoid"] != "02066"], self.legacy)


class Files(unittest.TestCase):
    def test_export_withdraws_manifest_writes_last_and_removes_stale(self):
        with tempfile.TemporaryDirectory() as root:
            states = {"06": [feature("06037", sq(0, 0), name="Los Angeles")], "12": [feature("12071", sq(0, 0), name="Lee")]}
            files = {ss: cb.state_file(ss, f, "test source", "L1") for ss, f in states.items()}
            sizes = cb.export_states(root, files, {"schemaVersion": 1, "loadId": "L1"})
            geo = f"{root}/geo/v1"
            doc = json.load(open(f"{geo}/states/06.json", encoding="utf-8"))
            self.assertEqual(doc["counties"][0], {"fips": "06037", "name": "Los Angeles County", "polygons": [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]]})
            self.assertEqual((doc["schemaVersion"], doc["stateFips"], doc["source"]), (1, "06", "test source"))
            man = json.load(open(f"{geo}/manifest.json", encoding="utf-8"))
            self.assertEqual([s["stateFips"] for s in man["states"]], ["06", "12"])
            self.assertEqual(man["states"][0]["bytes"], sizes["06"])
            cb.export_states(root, {"06": files["06"]}, {"schemaVersion": 1, "loadId": "L2"})
            self.assertEqual(sorted(os.listdir(f"{geo}/states")), ["06.json"])
            self.assertEqual(json.load(open(f"{geo}/manifest.json", encoding="utf-8"))["loadId"], "L2")

    def test_store_raw_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as root:
            p1 = cb.store_raw(root, 2025, "5m", b"one", {"a": 1})
            p2 = cb.store_raw(root, 2025, "5m", b"two", {"a": 2})
            self.assertNotEqual(p1, p2)
            self.assertTrue(p1.endswith("/cb_2025_us_county_5m.zip"))
            self.assertEqual(open(p1, "rb").read(), b"one")
            self.assertEqual(json.load(open(p1 + ".provenance.json"))["a"], 1)

    def test_fetch_retries_then_fails(self):
        calls = []

        class Resp:
            headers = {"Last-Modified": "Thu, 23 Apr 2026 10:00:00 GMT"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"zip"

        def flaky(req):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise OSError("timeout")
            return Resp()

        data, headers = cb.fetch("https://example.invalid/x.zip", opener=flaky, sleep=lambda s: None)
        self.assertEqual((data, headers["last-modified"], len(calls)), (b"zip", "Thu, 23 Apr 2026 10:00:00 GMT", 3))
        with self.assertRaises(cb.LoadError):
            cb.fetch("https://example.invalid/x.zip", opener=lambda r: (_ for _ in ()).throw(OSError("down")), sleep=lambda s: None)

    def test_urls_and_args(self):
        self.assertEqual(cb.source_url(2025, "5m"), "https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_5m.zip")
        self.assertEqual(cb.source_url(2021, "5m"), "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_county_5m.zip")
        a = cb.parse_args([])
        self.assertEqual((a.vintage, a.legacy_ct_vintage, a.scale, a.source_dir), (2025, 2021, "5m", None))
        for bad in (["--catalog", "x;drop"], ["--raw-volume", "/tmp/x"], ["--scale", "1m"], ["--vintage", "2020"], ["--legacy-ct-vintage", "2022"]):
            with self.assertRaises(SystemExit):
                cb.parse_args(bad)
        self.assertEqual(cb.table("users", "tom_jacobson", "county_boundaries"), "users.tom_jacobson.census_county_boundaries")
        with self.assertRaises(ValueError):
            cb.table("users", "tom`x", "y")


if __name__ == "__main__":
    unittest.main()
