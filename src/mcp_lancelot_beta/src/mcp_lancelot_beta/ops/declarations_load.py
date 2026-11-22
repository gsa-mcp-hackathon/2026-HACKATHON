"""FEMA declaration areas for the Choropleth square image (BUILD_PLAN D44).

For every disaster in the latest Choropleth snapshot (choropleth_data/manifest.json
-> snapshots/<latest>/index.json), reads OpenFEMA FemaWebDisasterDeclarations (v1:
shapefileUrl, hash) and DisasterDeclarationsSummaries (v2: official declarationTitle,
declarationType), downloads the declaration area shapefile gis.fema.gov/maps/dec_<n>.zip,
and writes one JSON file per disaster to the volume:

  declarations/v1/disasters/<disaster_number>.json   title, state, designations, affected counties
  declarations/v1/manifest.json                      written last: every disaster, status, counts

Affected rule (user, 2026-11-12): a county is affected if its designation includes
Individual Assistance (code starts with IA) or Public Assistance with any category other
than B (PA with no category letters counts). Blank or PA Category B only = not affected.
Designated areas without a county FIPS (tribal lands) are kept as outlines (extraAreas).

Format quirks handled: zip member names vary (dec_4673_amd12.shp), field names are lower
case in newer files and upper case in older ones, and some files hold every county of the
state with only some designated.

A disaster whose FEMA record hash and shapefile URL are unchanged since the last run keeps
its previous file (no download). Called by ops/openfema_load.py after the snapshot is
committed; also runnable on its own:
  declarations_load.py [--volume /Volumes/users/tom_jacobson/choropleth_data] [--force] [--only 4856,4673]

Plain Python (requests is the only non-standard import, used only for HTTP), so it is unit
tested by test/test_declarations_load.py without network.
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import sys
import time
import uuid
import zipfile
from collections import Counter

# __file__ is not defined when a Databricks job runs a file as a python task.
_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0] or "."))
if not os.path.isfile(os.path.join(_HERE, "county_boundaries_load.py")):
    _HERE = "/Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-beta/ops"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from county_boundaries_load import LoadError as ShapeError, read_dbf, read_shp, round_polygons, shapefile_polygons  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_VOLUME = "/Volumes/users/tom_jacobson/choropleth_data"
FEMA_WEB_URL = "https://www.fema.gov/api/open/v1/FemaWebDisasterDeclarations"
SUMMARIES_URL = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
PAGE_SIZE = 1000
HTTP_TIMEOUT_S = 120
HTTP_ATTEMPTS = 3
RETRY_SLEEP_S = (5, 15, 45)
USER_AGENT = "mcp-lancelot-beta declarations load (Databricks job)"
POLY_DIGITS = 4                  # ~10 m; outlines only, drawn at 1000 px
MAX_FAILED_SHARE = 0.10          # more failed downloads or parses than this fails the run
FIPS = re.compile(r"\d{5}")
CODE = re.compile(r"(IA)?(PA((?:[A-G](?:-[A-G])?)*))?")
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
TYPE_CODES = {"DR", "EM", "FM"}
# USPS code -> state FIPS, for declarations with no county rows (tribal-only declarations).
STATE_FIPS = dict(zip(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH "
    "OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU MP PR VI FM MH PW".split(),
    "01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 "
    "40 41 42 44 45 46 47 48 49 50 51 53 54 55 56 60 66 69 72 78 64 68 70".split()))

OK, NO_RECORD, NO_URL, FETCH_FAILED, PARSE_FAILED = "OK", "NO_DECLARATION_RECORD", "NO_SHAPEFILE_URL", "FETCH_FAILED", "PARSE_FAILED"


class LoadError(Exception):
    """The run cannot produce trustworthy files; the job fails."""


# ---------------------------------------------------------------------------
# Rules (pure)
# ---------------------------------------------------------------------------

def parse_designation(code):
    """FEMA designation code -> {code, ia, pa, categories, affected, recognized}.

    IAPAA-G -> IA and PA A-G; PAAB -> PA A and B; PAB -> PA B only (not affected);
    IA / IAPA / PA -> affected; blank -> not affected."""
    c = (code or "").strip().upper()
    m = CODE.fullmatch(c)
    recognized = m is not None
    if m:
        ia, pa, letters = bool(m.group(1)), m.group(2) is not None, m.group(3) or ""
    else:  # unknown shape: still honor IA / PA if present, and report the code
        ia, pa = c.startswith("IA"), "PA" in c
        tail = c.split("PA", 1)[1] if pa else ""
        letters = "".join(re.findall(r"[A-G](?:-[A-G])?", tail))
    cats = set()
    for a, b in re.findall(r"([A-G])(?:-([A-G]))?", letters):
        cats.update(chr(x) for x in range(ord(a), ord(b or a) + 1))
    affected = ia or (pa and (not cats or bool(cats - {"B"})))
    return {"code": c, "ia": ia, "pa": pa, "categories": sorted(cats), "affected": affected,
            "recognized": recognized or c == ""}


def title_case(raw):
    """FEMA's upper-case title -> 'Wildfires and Straight-line Winds', '59th Presidential ...'."""
    words, parts = [], (raw or "").split()
    for i, w in enumerate(parts):
        low = w.lower()
        if 0 < i < len(parts) - 1 and low in SMALL_WORDS:
            words.append(low)
            continue
        words.append(low[:1].upper() + low[1:] if low[:1].isalpha() else low)
    return " ".join(words)


def format_title(type_code, disaster_number, state, raw_title):
    code = type_code if type_code in TYPE_CODES else "DR"
    head = f"{code}-{disaster_number}-{state}" if state else f"{code}-{disaster_number}"
    name = title_case(raw_title)
    return f"{head} {name}" if name else head


AMENDMENT = re.compile(r"_amd(\d+)$", re.IGNORECASE)


def read_declaration_zip(data):
    """-> {records: [(attrs, rings)], members, stem}. Some zips hold one shapefile per
    amendment (dec_4861_amd1/_amd3/_amd4, or dec_4933 + dec_4933_amd2): the highest
    amendment is the current declaration and is the one read (no _amd suffix = 0)."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        stems = {}
        for n in names:
            low = n.lower()
            for ext in (".shp", ".dbf", ".cpg"):
                if low.endswith(ext):
                    stems.setdefault(n[:-len(ext)], {})[ext] = n
        usable = [s for s, parts in stems.items() if ".shp" in parts and ".dbf" in parts]
        if not usable:
            raise ShapeError(f"no .shp with a matching .dbf in {len(names)} members")

        def amendment(stem):
            m = AMENDMENT.search(os.path.basename(stem))
            return int(m.group(1)) if m else 0
        best = max(usable, key=lambda s: (amendment(s), s))
        parts = stems[best]
        encoding = zf.read(parts[".cpg"]).decode("ascii", "replace").strip() if ".cpg" in parts else "utf-8"
        try:
            "x".encode(encoding)
        except LookupError:
            encoding = "utf-8"
        shapes = read_shp(zf.read(parts[".shp"]))
        attrs = read_dbf(zf.read(parts[".dbf"]), encoding)
    if len(shapes) != len(attrs):
        raise ShapeError(f".shp has {len(shapes)} records but .dbf has {len(attrs)}")
    records = [(a, s) for a, s in zip(attrs, shapes) if a is not None]
    return {"records": records, "members": sorted(names), "stem": best,
            "shapefiles": len(usable)}


def lower_keys(attrs):
    return {str(k).lower(): v for k, v in (attrs or {}).items()}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def designations(records):
    """[(attrs, rings)] from read_zip -> (counties, extra_areas, codes, notes).

    counties: one entry per county FIPS (duplicate rows merged: affected if any row is).
    extra_areas: designated, affected rows without a county FIPS (tribal lands), as polygons."""
    by_fips, extra, codes, notes = {}, [], Counter(), []
    for attrs, rings in records:
        a = lower_keys(attrs)
        d = parse_designation(a.get("designate"))
        codes[d["code"]] += 1
        fips = str(a.get("fips") or "").strip()
        name = str(a.get("name") or "").strip()
        if FIPS.fullmatch(fips):
            cur = by_fips.get(fips)
            if cur is None:
                by_fips[fips] = {"fips": fips, "name": name, "designate": d["code"], "affected": d["affected"]}
            else:
                if d["affected"] and not cur["affected"]:
                    cur["affected"], cur["designate"] = True, d["code"]
                elif not cur["designate"]:
                    cur["designate"] = d["code"]
        elif d["affected"]:
            if not rings:
                notes.append(f"{name or '(no name)'}: designated but has no shape")
                continue
            try:
                polys = round_polygons(shapefile_polygons(rings), POLY_DIGITS)
            except ShapeError as err:
                notes.append(f"{name or '(no name)'}: {err}")
                continue
            extra.append({"name": name, "designate": d["code"], "polygons": polys})
    counties = [by_fips[k] for k in sorted(by_fips)]
    return counties, extra, codes, notes


def state_fips_of(counties):
    c = Counter(x["fips"][:2] for x in counties)
    return c.most_common(1)[0][0] if c else None


def base_doc(n, web, summary, load_id, retrieved_at):
    state = (summary or {}).get("state") or (web or {}).get("stateCode")
    raw_title = (summary or {}).get("declarationTitle") or (web or {}).get("disasterName") or ""
    type_code = (summary or {}).get("declarationType")
    return {
        "schemaVersion": SCHEMA_VERSION, "disasterNumber": n, "loadId": load_id, "retrievedAt": retrieved_at,
        "status": None, "statusDetail": None,
        "declarationType": type_code, "stateCode": state, "stateFips": None,
        "declarationTitle": raw_title, "title": format_title(type_code, n, state, raw_title),
        "source": {
            "femaWebHash": (web or {}).get("hash"), "femaWebLastRefresh": (web or {}).get("lastRefresh"),
            "shapefileUrl": (web or {}).get("shapefileUrl"), "zipBytes": None, "zipSha256": None,
            "zipMembers": None,
        },
        "currentAmendment": None, "counties": [], "affectedFips": [], "extraAreas": [],
        "designationCodes": {}, "unrecognizedCodes": [], "notes": [],
    }


def declaration_doc(n, web, summary, zip_bytes, load_id, retrieved_at):
    """Pure: the file for one disaster from its zip bytes. Parse errors -> status PARSE_FAILED."""
    doc = base_doc(n, web, summary, load_id, retrieved_at)
    doc["source"]["zipBytes"] = len(zip_bytes)
    doc["source"]["zipSha256"] = sha256(zip_bytes)
    try:
        parsed = read_declaration_zip(zip_bytes)
    except Exception as err:  # noqa: BLE001 - any bad zip is a per-disaster failure
        doc["status"], doc["statusDetail"] = PARSE_FAILED, f"{type(err).__name__}: {err}"[:300]
        return doc
    doc["source"]["zipMembers"] = parsed["members"]
    doc["source"]["shapefileUsed"] = parsed["stem"]
    doc["source"]["shapefilesInZip"] = parsed["shapefiles"]
    counties, extra, codes, notes = designations(parsed["records"])
    amds = sorted({str(lower_keys(a).get("curr_amd") or "").strip() for a, _ in parsed["records"]} - {""})
    doc.update({
        "status": OK, "stateFips": state_fips_of(counties) or STATE_FIPS.get(doc["stateCode"] or ""), "currentAmendment": amds[-1] if len(amds) == 1 else (amds or None),
        "counties": counties, "affectedFips": [c["fips"] for c in counties if c["affected"]],
        "extraAreas": extra, "designationCodes": dict(sorted(codes.items())),
        "unrecognizedCodes": sorted(c for c in codes if not parse_designation(c)["recognized"]),
        "notes": notes,
    })
    return doc


def reusable(previous, web):
    """The previous file can be kept when FEMA's record and URL are unchanged."""
    return bool(previous and web and previous.get("schemaVersion") == SCHEMA_VERSION
                and previous.get("status") == OK
                and previous.get("source", {}).get("femaWebHash") == web.get("hash")
                and previous.get("source", {}).get("shapefileUrl") == web.get("shapefileUrl"))


def manifest_entry(doc, nbytes, reused):
    return {"disasterNumber": doc["disasterNumber"], "status": doc["status"], "title": doc["title"],
            "stateCode": doc["stateCode"], "counties": len(doc["counties"]), "affected": len(doc["affectedFips"]),
            "extraAreas": len(doc["extraAreas"]), "bytes": nbytes, "reused": reused}


def check_failures(entries, max_share=MAX_FAILED_SHARE):
    failed = [e for e in entries if e["status"] in (FETCH_FAILED, PARSE_FAILED)]
    if entries and len(failed) / len(entries) > max_share:
        raise LoadError(f"{len(failed)} of {len(entries)} disasters failed to download or parse: "
                        f"{[(e['disasterNumber'], e['status']) for e in failed[:10]]}")
    return failed


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_bytes(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "wb") as fh:
            fh.write(data)
        try:
            os.remove(tmp)
        except OSError:
            pass


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _retry(fn, what, sleep=time.sleep):
    last = None
    for attempt in range(HTTP_ATTEMPTS):
        try:
            return fn()
        except Exception as err:  # noqa: BLE001 - report the last one
            last = err
            if attempt < HTTP_ATTEMPTS - 1:
                sleep(RETRY_SLEEP_S[attempt])
    raise LoadError(f"cannot fetch {what}: {last}")


def http_json(url, params):
    import requests
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.json()


def http_bytes(url):
    import requests
    resp = requests.get(url, timeout=HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def fetch_all(get_json, url, entity, flt, select=None, sleep=time.sleep):
    out, skip = [], 0
    while True:
        params = {"$filter": flt, "$top": PAGE_SIZE, "$skip": skip}
        if select:
            params["$select"] = select
        rows = _retry(lambda: get_json(url, params), f"{entity} skip {skip}", sleep)[entity]
        out.extend(rows)
        if len(rows) < PAGE_SIZE:
            return out
        skip += PAGE_SIZE


def latest_disasters(volume):
    manifest = read_json(f"{volume}/manifest.json")
    if not manifest or not manifest.get("latest"):
        raise LoadError("choropleth_data/manifest.json is missing or lists no latest snapshot")
    index = read_json(f"{volume}/snapshots/{manifest['latest']}/index.json")
    if not index or not isinstance(index.get("disasters"), list):
        raise LoadError(f"index.json for snapshot {manifest['latest']} is missing")
    since = manifest.get("declarationsSince") or "2021-01-01"
    return manifest["latest"], since, sorted(int(d["disasterNumber"]) for d in index["disasters"])


def run(volume=DEFAULT_VOLUME, only=None, force=False, get_json=http_json, get_bytes=http_bytes, sleep=time.sleep):
    """-> summary dict. Writes disaster files, then the manifest last."""
    t0 = time.time()
    snapshot, since, numbers = latest_disasters(volume)
    if only:
        numbers = [n for n in numbers if n in set(only)]
    load_id = f"decl-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    # Declarations a few months before `since` can still have projects; the filter is generous.
    flt = f"declarationDate ge '{int(since[:4]) - 1}{since[4:]}'"
    web = {r["disasterNumber"]: r for r in fetch_all(get_json, FEMA_WEB_URL, "FemaWebDisasterDeclarations", flt, sleep=sleep)}
    summaries = {}
    for r in fetch_all(get_json, SUMMARIES_URL, "DisasterDeclarationsSummaries", flt,
                       select="disasterNumber,declarationTitle,declarationType,state", sleep=sleep):
        summaries.setdefault(r["disasterNumber"], r)

    base = f"{volume}/declarations/v{SCHEMA_VERSION}"
    os.makedirs(f"{base}/disasters", exist_ok=True)
    previous_manifest = read_json(f"{base}/manifest.json")
    try:
        os.remove(f"{base}/manifest.json")   # withdrawn while files are rewritten
    except FileNotFoundError:
        pass

    entries, downloads = [], 0
    for n in numbers:
        path = f"{base}/disasters/{n}.json"
        w, s = web.get(n), summaries.get(n)
        prev = None if force else read_json(path)
        if reusable(prev, w):
            entries.append(manifest_entry(prev, os.path.getsize(path), True))
            continue
        if w is None:
            doc = base_doc(n, None, s, load_id, retrieved_at)
            doc["status"], doc["statusDetail"] = NO_RECORD, "not in FemaWebDisasterDeclarations"
        elif not w.get("shapefileUrl"):
            doc = base_doc(n, w, s, load_id, retrieved_at)
            doc["status"], doc["statusDetail"] = NO_URL, "FemaWebDisasterDeclarations has no shapefileUrl"
        else:
            try:
                data = _retry(lambda: get_bytes(w["shapefileUrl"]), w["shapefileUrl"], sleep)
                downloads += 1
                doc = declaration_doc(n, w, s, data, load_id, retrieved_at)
            except LoadError as err:
                doc = base_doc(n, w, s, load_id, retrieved_at)
                doc["status"], doc["statusDetail"] = FETCH_FAILED, str(err)[:300]
        text = dumps(doc).encode("utf-8")
        write_bytes(path, text)
        entries.append(manifest_entry(doc, len(text), False))

    if only and previous_manifest:  # a partial run keeps the other disasters' entries
        done = {e["disasterNumber"] for e in entries}
        entries += [e for e in previous_manifest.get("disasters") or [] if e["disasterNumber"] not in done]
        entries.sort(key=lambda e: e["disasterNumber"])
    failed = check_failures(entries)
    statuses = Counter(e["status"] for e in entries)
    unrecognized = Counter()
    for e in entries:
        doc = read_json(f"{base}/disasters/{e['disasterNumber']}.json") or {}
        for c in doc.get("unrecognizedCodes") or []:
            unrecognized[c] += 1
    manifest = {
        "schemaVersion": SCHEMA_VERSION, "loadId": load_id, "generatedAt": retrieved_at, "snapshot": snapshot,
        "declarationsSince": since, "disasters": entries, "statuses": dict(statuses),
        "downloads": downloads, "reused": sum(1 for e in entries if e["reused"]),
        "unrecognizedCodes": dict(unrecognized),
        "previousLoadId": (previous_manifest or {}).get("loadId"),
        "rule": "affected = IA, or PA with any category other than B (bare PA counts); blank or PA B only = not affected",
    }
    write_bytes(f"{base}/manifest.json", (json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    summary = {"loadId": load_id, "disasters": len(entries), "statuses": dict(statuses), "downloads": downloads,
               "reused": manifest["reused"], "failed": [(e["disasterNumber"], e["status"]) for e in failed],
               "unrecognizedCodes": dict(unrecognized), "seconds": round(time.time() - t0, 1)}
    print(f"declarations: {summary}")
    return summary


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--volume", default=DEFAULT_VOLUME)
    p.add_argument("--force", action="store_true", help="download every file even if FEMA's record is unchanged")
    p.add_argument("--only", default=None, help="comma-separated disaster numbers (others keep their files)")
    args = p.parse_args(argv)
    if not args.volume.startswith("/Volumes/") or args.volume.count("/") < 4:
        p.error("--volume must be a /Volumes/<catalog>/<schema>/<volume> path")
    args.volume = args.volume.rstrip("/")
    if args.only:
        try:
            args.only = [int(x) for x in args.only.split(",") if x.strip()]
        except ValueError:
            p.error("--only must be comma-separated disaster numbers")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run(args.volume, only=args.only, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
