"""Load U.S. Census county boundaries for the Choropleth widget (BUILD_PLAN D42, D43).

Fetches (or reads user-uploaded) Census cartographic boundary zips, keeps them
with provenance in a volume, writes Delta tables (boundaries, FEMA crosswalk,
load log), and exports one shape file per state that the app reads:

  <export>/geo/v1/states/<SS>.json   {schemaVersion, stateFips, source, loadId, counties: [{fips, name, polygons}]}
  <export>/geo/v1/manifest.json      written last; withdrawn before any state file is rewritten

Standard library only (own zip/shapefile/dBASE readers); Spark is used only
for tables, through the DataFrame and DeltaTable APIs (no SQL strings).
Everything above the "Spark part" line is plain Python and unit-tested
(test/test_county_boundaries_load.py).
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import struct
import sys
import time
import urllib.request
import uuid
import zipfile
from collections import Counter, defaultdict

CENSUS_BASE = "https://www2.census.gov/geo/tiger"
SCALES = ("500k", "5m", "20m")
SCALE_LABEL = {"500k": "1:500,000", "5m": "1:5,000,000", "20m": "1:20,000,000"}
DEFAULT_RAW_VOLUME = "/Volumes/users/tom_jacobson/census_boundaries"
DEFAULT_EXPORT_VOLUME = "/Volumes/users/tom_jacobson/choropleth_data"
GEO_SCHEMA_VERSION = 1
DIGITS = 5                      # ~1 m; applied to every vertex the same way, so shared vertices stay shared
FETCH_TIMEOUT_S = 180
FETCH_ATTEMPTS = 3
RETRY_SLEEP_S = (10, 30, 90)
USER_AGENT = "mcp-lancelot-beta county boundaries load (Databricks job)"
TABLE_PREFIX = "census_"
IDENTIFIER = re.compile(r"[A-Za-z0-9_]{1,255}")
GEOID = re.compile(r"\d{5}")

PRIMARY_RANGE = (3200, 3300)    # 50 states + DC + PR + 4 island territories
ISLAND_STATES = {"15", "60", "66", "69", "78"}   # HI, AS, GU, MP, VI: counties need not touch
NEIGHBOR_SHARE_MIN = 0.90
LEGACY_AREA_TOLERANCE = 0.02

# State files whose counties come from an older vintage, because FEMA PA data
# still uses those codes (checked 2026-11-06: CT only 09001-09015).
LEGACY_STATES = {"09": "legacy_ct_vintage"}
# Shapes FEMA still uses that the primary vintage split up: target <- parts.
DISSOLVES = {"02261": ("02063", "02066")}
DISSOLVE_NAMES = {"02261": "Valdez-Cordova Census Area"}
# Obsolete codes FEMA still uses for a county that exists under a newer code:
# fema code -> (shape geoid, reason). Found by the first load (2026-11-06).
RECODES = {
    "02232": ("02105", "FEMA labels code 232 'Hoonah-Angoon Census Area' (DR-4585); 232 was Skagway-Hoonah-Angoon until 2007, "
                       "when it split into Skagway (02230, which FEMA also uses) and Hoonah-Angoon (02105)"),
}


class LoadError(Exception):
    pass


def source_url(year, scale):
    return f"{CENSUS_BASE}/GENZ{year}/shp/{source_file(year, scale)}"


def source_file(year, scale):
    return f"cb_{year}_us_county_{scale}.zip"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Readers: zip, shapefile (.shp polygons), dBASE (.dbf)
# ---------------------------------------------------------------------------

def read_shp(data):
    """-> one entry per record: None (null shape) or a list of rings [(x, y), ...]."""
    if len(data) < 100 or struct.unpack(">i", data[0:4])[0] != 9994:
        raise LoadError("not a shapefile (.shp header)")
    if struct.unpack("<i", data[32:36])[0] not in (0, 5):
        raise LoadError("shapefile is not of type Polygon")
    out, pos = [], 100
    while pos + 8 <= len(data):
        _num, words = struct.unpack(">ii", data[pos:pos + 8])
        pos += 8
        end = pos + words * 2
        if end > len(data):
            raise LoadError("truncated .shp record")
        kind = struct.unpack("<i", data[pos:pos + 4])[0]
        if kind == 0:
            out.append(None)
        elif kind == 5:
            nparts, npoints = struct.unpack("<ii", data[pos + 36:pos + 44])
            parts = struct.unpack(f"<{nparts}i", data[pos + 44:pos + 44 + 4 * nparts])
            p0 = pos + 44 + 4 * nparts
            flat = struct.unpack(f"<{2 * npoints}d", data[p0:p0 + 16 * npoints])
            pts = list(zip(flat[0::2], flat[1::2]))
            bounds = list(parts) + [npoints]
            out.append([pts[bounds[i]:bounds[i + 1]] for i in range(nparts)])
        else:
            raise LoadError(f"unsupported shape type {kind} in .shp")
        pos = end
    return out


def read_dbf(data, encoding="utf-8"):
    """-> one dict per record (None for deleted records). Widths are in bytes."""
    if len(data) < 33:
        raise LoadError("not a dBASE file")
    count = struct.unpack("<I", data[4:8])[0]
    header_len, record_len = struct.unpack("<HH", data[8:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\x00")[0].decode("ascii")
        fields.append((name, chr(data[pos + 11]), data[pos + 16]))
        pos += 32
    rows, pos = [], header_len
    for _ in range(count):
        rec = data[pos:pos + record_len]
        pos += record_len
        if rec[:1] == b"*":
            rows.append(None)
            continue
        row, off = {}, 1
        for name, kind, width in fields:
            raw = rec[off:off + width].decode(encoding).strip()
            off += width
            if kind in ("N", "F"):
                row[name] = int(raw) if re.fullmatch(r"-?\d+", raw) else (float(raw) if raw else None)
            else:
                row[name] = raw
        rows.append(row)
    return rows


def read_zip(data):
    """-> {records: [(attrs, rings)], prj, members}; exactly one .shp/.dbf/.prj required."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        pick = {}
        for ext in (".shp", ".dbf", ".prj", ".cpg"):
            found = [n for n in names if n.lower().endswith(ext)]
            if ext != ".cpg" and len(found) != 1:
                raise LoadError(f"zip must hold exactly one {ext} file, found {len(found)}")
            pick[ext] = zf.read(found[0]) if found else None
    encoding = pick[".cpg"].decode("ascii").strip() if pick[".cpg"] else "utf-8"
    shapes = read_shp(pick[".shp"])
    attrs = read_dbf(pick[".dbf"], encoding)
    if len(shapes) != len(attrs):
        raise LoadError(f".shp has {len(shapes)} records but .dbf has {len(attrs)}")
    records = [(a, s) for a, s in zip(attrs, shapes) if a is not None]
    return {"records": records, "prj": pick[".prj"].decode("utf-8", "replace"), "members": sorted(names)}


# ---------------------------------------------------------------------------
# Geometry (lon/lat, planar math; areas in square degrees, used only as ratios)
# ---------------------------------------------------------------------------

def ring_area(ring):
    """Signed shoelace area: positive = counter-clockwise."""
    s = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        s += x0 * y1 - x1 * y0
    return s / 2.0


def point_in_ring(x, y, ring):
    inside = False
    for (xi, yi), (xj, yj) in zip(ring, ring[1:]):
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
    return inside


def _inside_point(ring, other):
    """A vertex of ring that is not a vertex of other (touching rings share some)."""
    verts = set(other)
    for p in ring:
        if p not in verts:
            return p
    return ring[0]


def assemble(outers, holes):
    """Outer rings CCW, holes CW (RFC 7946); each hole goes to the smallest outer containing it."""
    polys = [[o] for o in outers]
    for h in holes:
        best = None
        for i, o in enumerate(outers):
            x, y = _inside_point(h, o)
            if point_in_ring(x, y, o) and (best is None or abs(ring_area(o)) < abs(ring_area(outers[best]))):
                best = i
        if best is None:
            raise LoadError("hole outside every outer ring")
        polys[best].append(h)
    return polys


def close(ring):
    return ring if ring and ring[0] == ring[-1] else ring + ring[:1]


def shapefile_polygons(rings):
    """Shapefile rings (outer clockwise, holes counter-clockwise) -> RFC 7946 polygons."""
    rings = [close(list(r)) for r in rings if len(r) >= 3]
    rings = [list(reversed(r)) for r in rings]          # outer now CCW, holes CW
    outers = [r for r in rings if ring_area(r) > 0]
    holes = [r for r in rings if ring_area(r) < 0]
    if not outers:
        raise LoadError("polygon without an outer ring")
    return assemble(outers, holes)


def round_polygons(polys, digits=DIGITS):
    out = []
    for poly in polys:
        rings = []
        for k, ring in enumerate(poly):
            pts = []
            for x, y in ring:
                p = (round(x, digits), round(y, digits))
                if not pts or pts[-1] != p:
                    pts.append(p)
            pts = close(pts)
            if len(pts) >= 4 and ring_area(pts) != 0:
                rings.append(pts)
            elif k == 0:
                rings = None                                   # outer ring collapsed: drop polygon
                break
        if rings:
            out.append(rings)
    return out


def polygons_area(polys):
    return sum(ring_area(r) for poly in polys for r in poly)


def vertex_count(polys):
    return sum(len(r) for poly in polys for r in poly)


def dissolve(polygon_sets):
    """Union of polygon sets that share exact boundary vertices: shared edges appear
    once in each direction and cancel; the rest are chained back into rings."""
    edges = Counter()
    for polys in polygon_sets:
        for poly in polys:
            for ring in poly:
                for a, b in zip(ring, ring[1:]):
                    edges[(a, b)] += 1
    nxt = defaultdict(list)
    for (a, b), n in edges.items():
        keep = n - min(n, edges.get((b, a), 0))
        nxt[a].extend([b] * keep)
    nxt = {k: v for k, v in nxt.items() if v}
    rings = []
    while nxt:
        start = min(nxt)
        ring, cur = [start], start
        while True:
            if cur not in nxt:
                raise LoadError("dissolve left an open ring (boundaries do not share vertices)")
            b = nxt[cur].pop()
            if not nxt[cur]:
                del nxt[cur]
            ring.append(b)
            cur = b
            if cur == start:
                break
        rings.append(ring)
    outers = [r for r in rings if ring_area(r) > 0]
    holes = [r for r in rings if ring_area(r) < 0]
    return assemble(outers, holes)


def adjacency(features):
    """geoid -> set of neighbor geoids; neighbors share at least two vertices (same rule as geo.mjs)."""
    by_vertex = defaultdict(set)
    for f in features:
        for poly in f["polygons"]:
            for ring in poly:
                for p in ring:
                    by_vertex[p].add(f["geoid"])
    shared = Counter()
    for ids in by_vertex.values():
        if len(ids) > 1:
            ids = sorted(ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    shared[(ids[i], ids[j])] += 1
    adj = {f["geoid"]: set() for f in features}
    for (a, b), n in shared.items():
        if n >= 2:
            adj[a].add(b)
            adj[b].add(a)
    return adj


# ---------------------------------------------------------------------------
# Features, composition, crosswalk, checks
# ---------------------------------------------------------------------------

def build_features(parsed, vintage, scale):
    """-> (features, errors). A feature is one county with RFC 7946 polygons, rounded."""
    feats, errors, seen = [], [], set()
    for attrs, rings in parsed["records"]:
        geoid = str(attrs.get("GEOID", ""))
        statefp, countyfp = str(attrs.get("STATEFP", "")), str(attrs.get("COUNTYFP", ""))
        if not GEOID.fullmatch(geoid) or geoid != statefp + countyfp:
            errors.append(f"bad GEOID {geoid!r} (STATEFP {statefp!r}, COUNTYFP {countyfp!r})")
            continue
        if geoid in seen:
            errors.append(f"duplicate GEOID {geoid}")
            continue
        seen.add(geoid)
        polys = round_polygons(shapefile_polygons(rings)) if rings else []
        if not polys:
            errors.append(f"empty geometry for {geoid}")
            continue
        feats.append({
            "vintage": vintage, "scale": scale, "geoid": geoid, "statefp": statefp, "countyfp": countyfp,
            "stusps": attrs.get("STUSPS") or None, "name": attrs.get("NAME") or None,
            "namelsad": attrs.get("NAMELSAD") or attrs.get("NAME") or geoid, "lsad": attrs.get("LSAD") or None,
            "aland": attrs.get("ALAND"), "awater": attrs.get("AWATER"), "polygons": polys,
        })
    return feats, errors


def prj_is_nad83_geographic(prj):
    return "GEOGCS" in prj and "PROJCS" not in prj and ("North_American_1983" in prj or "NAD83" in prj)


def compose_states(primary, legacy):
    """primary: features; legacy: {state: features from the older vintage}.
    -> (states {SS: [features]}, rules {geoid: (rule, vintage, source_geoids)}, notes)"""
    states = defaultdict(list)
    for f in primary:
        states[f["statefp"]].append(f)
    rules, notes = {}, []
    for f in primary:
        rules[f["geoid"]] = ("IDENTITY", f["vintage"], [f["geoid"]])
    for ss, feats in legacy.items():
        if not feats:
            raise LoadError(f"no legacy counties for state {ss}")
        for f in states.get(ss, []):
            rules.pop(f["geoid"], None)
        states[ss] = list(feats)
        for f in feats:
            rules[f["geoid"]] = ("LEGACY_VINTAGE", f["vintage"], [f["geoid"]])
        notes.append(f"state {ss}: {len(feats)} counties from vintage {feats[0]['vintage']}")
    for target, parts in DISSOLVES.items():
        ss = target[:2]
        have = {f["geoid"]: f for f in states.get(ss, [])}
        missing = [p for p in parts if p not in have]
        if missing:
            raise LoadError(f"cannot build {target}: parts {missing} not in state {ss}")
        polys = dissolve([have[p]["polygons"] for p in parts])
        base = have[parts[0]]
        merged = {**base, "geoid": target, "countyfp": target[2:], "name": DISSOLVE_NAMES[target].rsplit(" ", 2)[0],
                  "namelsad": DISSOLVE_NAMES[target], "lsad": None, "polygons": polys,
                  "aland": sum(have[p]["aland"] or 0 for p in parts), "awater": sum(have[p]["awater"] or 0 for p in parts)}
        states[ss] = [f for f in states[ss] if f["geoid"] not in parts] + [merged]
        for p in parts:
            rules.pop(p, None)
        rules[target] = ("DISSOLVE", base["vintage"], list(parts))
        notes.append(f"{target} = dissolve of {', '.join(parts)}")
    for ss in states:
        states[ss].sort(key=lambda f: f["geoid"])
    return dict(states), rules, notes


def crosswalk(fema_rows, states, rules):
    """fema_rows: [{county_fips, county_name, projects, disasters}] -> crosswalk rows."""
    exported = {f["geoid"] for feats in states.values() for f in feats}
    out = []
    for r in sorted(fema_rows, key=lambda r: r["county_fips"]):
        fips = r["county_fips"]
        if fips in exported:
            rule, vintage, sources = rules[fips]
            out.append({**r, "rule": rule, "shape_geoid": fips, "shape_vintage": vintage, "source_geoids": sources})
        elif fips in RECODES and RECODES[fips][0] in exported:
            target = RECODES[fips][0]
            _rule, vintage, sources = rules[target]
            out.append({**r, "rule": "RECODE", "shape_geoid": target, "shape_vintage": vintage, "source_geoids": sources})
        else:
            out.append({**r, "rule": "UNMATCHED", "shape_geoid": None, "shape_vintage": None, "source_geoids": []})
    return out


def run_checks(sources, primary, primary_errors, legacy_states, legacy_errors, states, rules, cross):
    """-> list of {name, ok, detail}; any ok=False fails the load."""
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    for s in sources:
        add(f"projection:{s['file']}", prj_is_nad83_geographic(s["prj"]), "NAD83 geographic lon/lat" if prj_is_nad83_geographic(s["prj"]) else s["prj"][:200])
    add("primary:records", not primary_errors, primary_errors[:20] or "GEOIDs valid, unique, non-empty")
    add("legacy:records", not legacy_errors, legacy_errors[:20] or "GEOIDs valid, unique, non-empty")
    add("primary:count", PRIMARY_RANGE[0] <= len(primary) <= PRIMARY_RANGE[1], f"{len(primary)} features, expected {PRIMARY_RANGE[0]}-{PRIMARY_RANGE[1]}")

    by_state = defaultdict(list)
    for f in primary:
        by_state[f["statefp"]].append(f)
    for ss, feats in legacy_states.items():
        a_new = polygons_area([p for f in by_state.get(ss, []) for p in f["polygons"]])
        a_old = polygons_area([p for f in feats for p in f["polygons"]])
        ratio = a_old / a_new if a_new else 0
        add(f"legacy:area:{ss}", abs(ratio - 1) <= LEGACY_AREA_TOLERANCE, f"legacy/primary area ratio {ratio:.4f}")
    primary_by_id = {f["geoid"]: f for f in primary}
    for target, parts in DISSOLVES.items():
        merged = next((f for f in states.get(target[:2], []) if f["geoid"] == target), None)
        if merged is None:
            add(f"dissolve:{target}", False, "not built")
            continue
        expect = sum(polygons_area(primary_by_id[p]["polygons"]) for p in parts)
        got = polygons_area(merged["polygons"])
        before = sum(len(primary_by_id[p]["polygons"]) for p in parts)
        # area must be kept, and at least one shared border must have vanished
        add(f"dissolve:{target}", expect > 0 and abs(got - expect) <= 1e-9 * expect + 1e-12 and len(merged["polygons"]) < before,
            f"area {got:.6f} vs parts {expect:.6f}; {before} polygons before, {len(merged['polygons'])} after")

    # Neighbors across state lines count (Newport County, RI touches only Massachusetts).
    adj = adjacency([f for feats in states.values() for f in feats])
    lonely, weak = {}, []
    for ss, feats in sorted(states.items()):
        alone = sorted(f["geoid"] for f in feats if not adj[f["geoid"]])
        if alone:
            lonely[ss] = alone
        if ss not in ISLAND_STATES and len(feats) > 1:
            share = 1 - len(alone) / len(feats)
            if share < NEIGHBOR_SHARE_MIN:
                weak.append(f"{ss}: {share:.0%} of {len(feats)} counties have a neighbor")
    add("adjacency:shared-vertices", not weak, weak or "every non-island state: >= 90% of counties have a neighbor")
    unmatched = [f"{r['county_fips']} {r['county_name']}" for r in cross if r["rule"] == "UNMATCHED"]
    add("crosswalk:coverage", not unmatched, unmatched[:50] or f"all {len(cross)} FEMA county codes resolve")
    return checks, lonely


def state_file(ss, feats, source_text, load_id):
    have = {f["geoid"] for f in feats}
    aliases = {fema: target for fema, (target, _why) in sorted(RECODES.items()) if target in have}
    return {
        "schemaVersion": GEO_SCHEMA_VERSION, "stateFips": ss, "source": source_text, "loadId": load_id,
        "aliases": aliases,  # FEMA county code -> shape fips (crosswalk rule RECODE)
        "counties": [{"fips": f["geoid"], "name": f["namelsad"], "polygons": [[[list(p) for p in ring] for ring in poly] for poly in f["polygons"]]}
                     for f in feats],
    }


def source_text(feats, rules, scale):
    vintages = sorted({rules[f["geoid"]][1] for f in feats})
    text = f"U.S. Census Bureau cartographic boundary file, counties, {SCALE_LABEL[scale]}, {'/'.join(str(v) for v in vintages)}"
    dissolved = [g for g in (f["geoid"] for f in feats) if rules[g][0] == "DISSOLVE"]
    if dissolved:
        text += "; " + "; ".join(f"{g} = {' + '.join(rules[g][2])}" for g in dissolved)
    return text


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_bytes(path, data, atomic=True):
    tmp = f"{path}.tmp" if atomic else path
    with open(tmp, "wb") as fh:
        fh.write(data)
    if atomic:
        try:
            os.replace(tmp, path)
        except OSError:
            with open(path, "wb") as fh:
                fh.write(data)
            try:
                os.remove(tmp)
            except OSError:
                pass


def export_states(export_root, files, manifest):
    """Withdraw the manifest, write every state file, delete stale ones, write the manifest last."""
    geo = f"{export_root}/geo/v{GEO_SCHEMA_VERSION}"
    os.makedirs(f"{geo}/states", exist_ok=True)
    try:
        os.remove(f"{geo}/manifest.json")
    except FileNotFoundError:
        pass
    sizes = {}
    for ss, doc in sorted(files.items()):
        data = dumps(doc).encode("utf-8")
        write_bytes(f"{geo}/states/{ss}.json", data)
        sizes[ss] = len(data)
    for name in os.listdir(f"{geo}/states"):
        m = re.fullmatch(r"(\d{2})\.json", name)
        if m and m.group(1) not in files:
            os.remove(f"{geo}/states/{name}")
    manifest = {**manifest, "states": [{"stateFips": ss, "counties": len(files[ss]["counties"]), "bytes": sizes[ss]} for ss in sorted(files)]}
    write_bytes(f"{geo}/manifest.json", dumps(manifest).encode("utf-8"))
    return sizes


def store_raw(raw_root, year, scale, data, provenance):
    """Content-addressed: raw/GENZ<year>/<sha12>/<file>; never overwrites."""
    digest = sha256(data)
    folder = f"{raw_root}/raw/GENZ{year}/{digest[:12]}"
    os.makedirs(folder, exist_ok=True)
    path = f"{folder}/{source_file(year, scale)}"
    if not os.path.exists(path):
        write_bytes(path, data)
    write_bytes(f"{path}.provenance.json", (json.dumps(provenance, indent=2) + "\n").encode("utf-8"))
    return path


def fetch(url, opener=None, sleep=time.sleep):
    """-> (bytes, headers dict). 3 attempts."""
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S))
    last = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with opener(req) as resp:
                return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except Exception as err:  # noqa: BLE001 - report the last one
            last = err
            if attempt < FETCH_ATTEMPTS - 1:
                sleep(RETRY_SLEEP_S[attempt])
    raise LoadError(f"cannot fetch {url}: {last}")


def now():
    return dt.datetime.now(dt.timezone.utc)


def table(catalog, schema, name):
    for part in (catalog, schema, name):
        if not IDENTIFIER.fullmatch(part):
            raise ValueError(f"not a plain identifier: {part!r}")
    return f"{catalog}.{schema}.{TABLE_PREFIX}{name}"


# ---------------------------------------------------------------------------
# Spark part (job only)
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--catalog", default="users")
    p.add_argument("--schema", default="tom_jacobson")
    p.add_argument("--vintage", default=2025, type=int)
    p.add_argument("--legacy-ct-vintage", default=2021, type=int)
    p.add_argument("--scale", default="5m", choices=SCALES)
    p.add_argument("--raw-volume", default=DEFAULT_RAW_VOLUME)
    p.add_argument("--export-volume", default=DEFAULT_EXPORT_VOLUME)
    p.add_argument("--source-dir", default=None, help="read cb_<year>_us_county_<scale>.zip from here instead of fetching")
    p.add_argument("--dry-run", action="store_true", help="fetch, parse and check; write only a DRY_RUN load-log row")
    args = p.parse_args(argv)
    for flag in ("catalog", "schema"):
        if not IDENTIFIER.fullmatch(getattr(args, flag)):
            p.error(f"--{flag} must contain only letters, digits and underscores")
    for flag in ("raw_volume", "export_volume", "source_dir"):
        v = getattr(args, flag)
        if v is not None:
            if not v.startswith("/Volumes/") or v.count("/") < 4:
                p.error(f"--{flag.replace('_', '-')} must be a /Volumes/<catalog>/<schema>/<volume> path")
            setattr(args, flag, v.rstrip("/"))
    if not (2010 <= args.legacy_ct_vintage <= 2021 < args.vintage <= 2100):
        p.error("--legacy-ct-vintage must be 2010-2021 and --vintage after 2021")
    return args


def obtain(year, scale, args):
    """-> (bytes, provenance)."""
    url = source_url(year, scale)
    retrieved = now().isoformat()
    if args.source_dir:
        path = f"{args.source_dir}/{source_file(year, scale)}"
        with open(path, "rb") as fh:
            data = fh.read()
        prov = {"origin": "upload", "path": path, "officialUrl": url, "retrievedAt": retrieved}
    else:
        data, headers = fetch(url)
        prov = {"origin": "fetch", "url": url, "retrievedAt": retrieved,
                "httpLastModified": headers.get("last-modified"), "httpEtag": headers.get("etag"),
                "httpContentLength": headers.get("content-length")}
    prov.update({"file": source_file(year, scale), "vintage": year, "scale": scale, "bytes": len(data), "sha256": sha256(data)})
    return data, prov


def _schemas():
    from pyspark.sql import types as T
    S, I, L, TS = T.StringType(), T.IntegerType(), T.LongType(), T.TimestampType()
    boundaries = [
        ("vintage", I, "Census vintage (boundaries as of 1 January of that year)"), ("scale", S, "500k, 5m or 20m"),
        ("geoid", S, "5-digit county FIPS (STATEFP + COUNTYFP)"), ("statefp", S, "2-digit state FIPS"),
        ("countyfp", S, "3-digit county FIPS"), ("stusps", S, "State postal code"), ("name", S, "County name"),
        ("namelsad", S, "County name with legal/statistical description"), ("lsad", S, "Legal/statistical area description code"),
        ("aland", L, "Land area, square meters (Census)"), ("awater", L, "Water area, square meters (Census)"),
        ("geometry_geojson", S, "GeoJSON MultiPolygon coordinates, lon/lat NAD83, RFC 7946 ring order, 5 decimals"),
        ("polygon_count", I, "Polygons"), ("vertex_count", I, "Vertices"),
        ("source_file", S, "Census zip file name"), ("source_sha256", S, "SHA-256 of the zip as loaded"),
        ("load_id", S, "Load that wrote the row"), ("loaded_at", TS, "Write time (UTC)"),
    ]
    cross = [
        ("fema_county_fips", S, "5-digit county code as in openfema_pa_projects_silver"), ("fema_county_name", S, "County name in FEMA data"),
        ("state_fips", S, "2-digit state FIPS"), ("projects", L, "Projects with this code in the FEMA snapshot"),
        ("disasters", L, "Disasters with this code"), ("rule", S, "IDENTITY, LEGACY_VINTAGE, DISSOLVE, RECODE or UNMATCHED"),
        ("shape_geoid", S, "County shape used on the map (NULL when UNMATCHED)"), ("shape_vintage", I, "Vintage of that shape"),
        ("source_geoids", T.ArrayType(S), "Census GEOIDs the shape was built from"),
        ("fema_snapshot_date", T.DateType(), "OpenFEMA snapshot the codes came from"), ("load_id", S, "Boundary load that wrote the row"),
    ]
    log = [
        ("load_id", S, "Load ID"), ("status", S, "SUCCEEDED, FAILED or DRY_RUN"), ("vintage", I, "Primary vintage"),
        ("legacy_ct_vintage", I, "Vintage used for Connecticut"), ("scale", S, "Scale"),
        ("sources_json", S, "Provenance of each zip (URL, bytes, SHA-256, HTTP headers)"),
        ("features", L, "Primary features"), ("exported_states", L, "State files written"), ("exported_bytes", L, "Bytes written"),
        ("checks_json", S, "Every check with result and detail"), ("notes", S, "Composition notes"),
        ("started_at", TS, "Start (UTC)"), ("finished_at", TS, "End (UTC)"), ("message", S, "Error or summary"),
    ]
    return boundaries, cross, log


COMMENTS = {
    "county_boundaries": "U.S. Census cartographic boundary counties, one row per county per vintage and scale, as loaded by ops/county_boundaries_load.py (BUILD_PLAN D43). Public domain; source: U.S. Census Bureau.",
    "fema_county_crosswalk": "Every county code in the latest OpenFEMA PA snapshot mapped to the county shape the Choropleth map uses (rule IDENTITY, LEGACY_VINTAGE, DISSOLVE, RECODE or UNMATCHED). BUILD_PLAN D43.",
    "boundaries_load_log": "County boundary loads, one row per run, with source provenance and every check (BUILD_PLAN D43).",
}


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    started = now()
    load_id = f"{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    print(f"load {load_id}: vintage {args.vintage}, CT {args.legacy_ct_vintage}, scale {args.scale}, "
          f"source {'upload ' + args.source_dir if args.source_dir else 'fetch'}, dry_run={args.dry_run}")

    from pyspark.sql import SparkSession, functions as F, types as T
    from delta.tables import DeltaTable
    spark = SparkSession.builder.getOrCreate()
    names = {n: table(args.catalog, args.schema, n) for n in COMMENTS}
    b_cols, c_cols, l_cols = _schemas()

    def ensure(key, cols):
        builder = DeltaTable.createIfNotExists(spark).tableName(names[key]).comment(COMMENTS[key])
        for n, typ, comment in cols:
            builder = builder.addColumn(n, typ, comment=comment)
        builder.execute()

    def schema_of(cols):
        return T.StructType([T.StructField(n, typ) for n, typ, _ in cols])

    sources, notes, checks, status, message = [], [], [], "FAILED", None
    features_n = exported_n = exported_bytes = None
    try:
        loaded = {}
        for year in (args.vintage, args.legacy_ct_vintage):
            t0 = time.time()
            data, prov = obtain(year, args.scale, args)
            parsed = read_zip(data)
            prov["members"] = parsed["members"]
            if not args.dry_run:
                prov["storedAt"] = store_raw(args.raw_volume, year, args.scale, data, prov)
            print(f"{prov['file']}: {prov['bytes']} bytes, sha256 {prov['sha256'][:16]}..., {len(parsed['records'])} records, {time.time() - t0:.1f} s")
            sources.append({**prov, "prj": parsed["prj"]})
            loaded[year] = (parsed, prov)

        primary, primary_errors = build_features(loaded[args.vintage][0], args.vintage, args.scale)
        legacy_all, legacy_errors = build_features(loaded[args.legacy_ct_vintage][0], args.legacy_ct_vintage, args.scale)
        legacy = {ss: [f for f in legacy_all if f["statefp"] == ss] for ss in LEGACY_STATES}
        states, rules, notes = compose_states(primary, legacy)
        features_n = len(primary)

        # FEMA county codes from the latest succeeded OpenFEMA snapshot
        log_t = f"{args.catalog}.{args.schema}.openfema_pa_load_log"
        silver_t = f"{args.catalog}.{args.schema}.openfema_pa_projects_silver"
        latest = (spark.table(log_t).filter(F.col("status") == "SUCCEEDED")
                  .agg(F.max("snapshot_date").alias("d")).collect()[0]["d"])
        if latest is None:
            raise LoadError("no SUCCEEDED OpenFEMA snapshot to check coverage against")
        fema = (spark.table(silver_t).filter((F.col("snapshot_date") == F.lit(latest)) & (F.col("geo_status") == "COUNTY"))
                .groupBy("county_fips").agg(F.first("county_name", ignorenulls=True).alias("county_name"),
                                            F.first("state_fips", ignorenulls=True).alias("state_fips"),
                                            F.count(F.lit(1)).alias("projects"), F.countDistinct("disaster_number").alias("disasters"))
                .collect())
        fema_rows = [{"county_fips": r["county_fips"], "county_name": r["county_name"], "state_fips": r["state_fips"],
                      "projects": int(r["projects"]), "disasters": int(r["disasters"])} for r in fema]
        cross = crosswalk(fema_rows, states, rules)
        checks, lonely = run_checks(sources, primary, primary_errors, legacy, legacy_errors, states, rules, cross)
        notes.append(f"FEMA snapshot {latest}: {len(cross)} county codes; rules {dict(Counter(r['rule'] for r in cross))}")
        notes.append(f"counties without a neighbor: {sum(len(v) for v in lonely.values())} "
                     f"({', '.join(f'{k}:{len(v)}' for k, v in sorted(lonely.items()))})")
        for c in checks:
            print(f"check {'PASS' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
        failed = [c["name"] for c in checks if not c["ok"]]
        if failed:
            raise LoadError(f"checks failed: {', '.join(failed)}")

        files = {ss: state_file(ss, feats, source_text(feats, rules, args.scale), load_id) for ss, feats in states.items()}
        if args.dry_run:
            status = "DRY_RUN"
            message = f"dry run: {len(files)} state files would be written"
            return 0

        written_at = now()
        ensure("county_boundaries", b_cols)
        b_rows = []
        for year in (args.vintage, args.legacy_ct_vintage):
            feats = primary if year == args.vintage else legacy_all
            prov = loaded[year][1]
            b_rows += [(f["vintage"], f["scale"], f["geoid"], f["statefp"], f["countyfp"], f["stusps"], f["name"], f["namelsad"],
                        f["lsad"], f["aland"], f["awater"], dumps(f["polygons"]), len(f["polygons"]), vertex_count(f["polygons"]),
                        prov["file"], prov["sha256"], load_id, written_at) for f in feats]
        bt = DeltaTable.forName(spark, names["county_boundaries"])
        for year in (args.vintage, args.legacy_ct_vintage):
            bt.delete((F.col("vintage") == F.lit(year)) & (F.col("scale") == F.lit(args.scale)))
        spark.createDataFrame(b_rows, schema_of(b_cols)).write.format("delta").mode("append").saveAsTable(names["county_boundaries"])

        ensure("fema_county_crosswalk", c_cols)
        c_rows = [(r["county_fips"], r["county_name"], r["state_fips"], r["projects"], r["disasters"], r["rule"], r["shape_geoid"],
                   r["shape_vintage"], r["source_geoids"], latest, load_id) for r in cross]
        spark.createDataFrame(c_rows, schema_of(c_cols)).write.format("delta").mode("overwrite").saveAsTable(names["fema_county_crosswalk"])

        manifest = {"schemaVersion": GEO_SCHEMA_VERSION, "loadId": load_id, "generatedAt": written_at.isoformat(),
                    "sources": [{k: s[k] for k in ("file", "vintage", "scale", "bytes", "sha256", "origin") if k in s} for s in sources],
                    "rules": {"legacyStates": {ss: args.legacy_ct_vintage for ss in LEGACY_STATES}, "dissolves": {k: list(v) for k, v in DISSOLVES.items()},
                              "recodes": {k: {"shape": v[0], "reason": v[1]} for k, v in RECODES.items()}}}
        sizes = export_states(args.export_volume, files, manifest)
        exported_n, exported_bytes = len(sizes), sum(sizes.values())
        biggest = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
        status = "SUCCEEDED"
        message = f"{exported_n} state files, {exported_bytes} bytes; largest {biggest}"
        print(message)
        return 0
    except Exception as err:
        message = f"{type(err).__name__}: {err}"
        print(f"load {load_id} FAILED: {message}")
        raise
    finally:
        ensure("boundaries_load_log", l_cols)
        row = [(load_id, status, args.vintage, args.legacy_ct_vintage, args.scale,
                dumps([{k: v for k, v in s.items() if k != "prj"} for s in sources]), features_n, exported_n, exported_bytes,
                dumps(checks), "\n".join(notes), started, now(), (message or "")[:4000])]
        spark.createDataFrame(row, schema_of(l_cols)).write.format("delta").mode("append").saveAsTable(names["boundaries_load_log"])


if __name__ == "__main__":
    # Databricks reports any SystemExit, even 0, as a failed run: exit only on failure.
    _rc = main()
    if _rc:
        sys.exit(_rc)
