"""OpenFEMA Public Assistance load for the Choropleth tool (BUILD_PLAN D34, D36, D39).

Loads OpenFEMA PublicAssistanceFundedProjectsDetails (v2) for declarations on or
after --since into managed Delta tables in <catalog>.<schema>:

  openfema_pa_projects_bronze      raw API rows, every field as a string
  openfema_pa_projects_silver      typed, whitelisted fields, cleaned titles, county FIPS
  openfema_pa_category_stats_gold  per snapshot/disaster/category: n, mean, stddev_pop
  openfema_pa_projects_gold        per project/snapshot: sigma, multiple of mean
  openfema_pa_load_log             one row per load attempt

and exports each snapshot as JSON files to the volume --volume (D41), which
the app reads with the Files API (no SQL warehouse is available, D40):

  snapshots/<YYYY-MM-DD>/disasters/<disaster_number>.json   one disaster
  snapshots/<YYYY-MM-DD>/index.json                          disasters in the snapshot
  manifest.json                                              available snapshots, latest

One snapshot per UTC day (snapshot_date). A same-day rerun replaces that day's
rows. The load-log row is written SUCCEEDED last, and only when every check
passes; the Choropleth tool treats the newest SUCCEEDED snapshot as "latest".
Snapshots older than --keep-days are deleted (never the newest SUCCEEDED one)
and their log rows marked EXPIRED. manifest.json is written last: the app uses
only snapshots it lists, and a same-day rerun first removes the day from it.

Statistics follow 2026h exactly: projectAmount, population standard deviation,
sigma = (amount - mean) / stddev, the project stays in its own baseline.
Baseline = one disaster + one damage category. Outliers are not precomputed
(sigma_threshold is a tool input).

Runs as the scheduled job "mcp-lancelot-beta OpenFEMA load". Usage:
  openfema_load.py [--catalog users] [--schema tom_jacobson] [--since 2021-01-01]
                   [--keep-days 90] [--min-ratio 0.5] [--snapshot-date YYYY-MM-DD]
                   [--volume /Volumes/users/tom_jacobson/choropleth_data] [--dry-run]
                   [--skip-declarations]
--dry-run fetches and validates but writes nothing. After the manifest, the run refreshes
declarations/v1 with ops/declarations_load.py (D44) unless --skip-declarations.

Everything above main() is plain Python with no Spark import, so it is unit
tested by test/test_openfema_load.py.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP

API_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
ENTITY = "PublicAssistanceFundedProjectsDetails"
PAGE_SIZE = 10_000          # OpenFEMA maximum $top
PAGE_TIMEOUT_S = 120
PAGE_ATTEMPTS = 3
RETRY_SLEEP_S = (5, 15, 45)
TITLE_MAX = 200
ZERO_STDDEV = 0.005         # below half a cent the category has no variation
TABLE_PREFIX = "openfema_pa_"
DEFAULT_VOLUME = "/Volumes/users/tom_jacobson/choropleth_data"
EXPORT_SCHEMA_VERSION = 1
# Catalog and schema are put into SQL text, so they must be plain identifiers.
IDENTIFIER = re.compile(r"[A-Za-z0-9_]{1,255}")

# The 25 fields of the v2 dataset, in API order (checked 2026-11-06).
SOURCE_FIELDS = (
    "disasterNumber", "declarationDate", "incidentType", "pwNumber", "applicationTitle",
    "applicantId", "damageCategoryCode", "damageCategoryDescrip", "projectStatus",
    "projectProcessStep", "projectSize", "county", "countyCode", "stateAbbreviation",
    "stateNumberCode", "projectAmount", "federalShareObligated", "totalObligated",
    "lastObligationDate", "firstObligationDate", "mitigationAmount", "gmProjectId",
    "gmApplicantId", "lastRefresh", "hash",
)

# Silver keeps only what the widget may show (D36 sanitization whitelist):
# no obligation fields, no hash, no Grants Manager IDs.
SILVER_COLUMNS = (
    ("snapshot_date", "date"), ("load_id", "string"),
    ("disaster_number", "int"), ("declaration_date", "date"), ("incident_type", "string"),
    ("pw_number", "int"), ("application_title", "string"), ("applicant_id", "string"),
    ("damage_category_code", "string"), ("damage_category_descrip", "string"),
    ("project_status", "string"), ("project_process_step", "string"), ("project_size", "string"),
    ("state_abbreviation", "string"), ("state_fips", "string"), ("county_name", "string"),
    ("county_fips", "string"), ("geo_status", "string"), ("is_statewide", "boolean"),
    ("project_amount", "decimal"), ("last_refresh", "timestamp"),
)

GEO_COUNTY, GEO_STATEWIDE, GEO_UNMAPPABLE = "COUNTY", "STATEWIDE", "UNMAPPABLE"


class LoadError(Exception):
    """A check failed; the load is recorded FAILED or REJECTED and the job fails."""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def page_params(since, skip, top=PAGE_SIZE):
    """OData parameters for one page. Ordered by unique keys so paging is stable."""
    return {
        "$filter": f"declarationDate ge '{since.isoformat()}T00:00:00.000z'",
        "$orderby": "gmProjectId,hash",
        "$top": top,
        "$skip": skip,
        "$inlinecount": "allpages",
    }


def fetch_page(get, params, sleep=time.sleep):
    """One page with retries. `get(params)` returns the decoded JSON body or raises."""
    last = None
    for attempt in range(PAGE_ATTEMPTS):
        try:
            body = get(params)
            rows = body[ENTITY]
            count = int(body["metadata"]["count"])
            return rows, count
        except Exception as err:  # network, HTTP, JSON, or shape error
            last = err
            if attempt + 1 < PAGE_ATTEMPTS:
                sleep(RETRY_SLEEP_S[attempt])
    raise LoadError(f"page at skip={params['$skip']} failed after {PAGE_ATTEMPTS} attempts: {last}")


def fetch_all(get, since, page_size=PAGE_SIZE, sleep=time.sleep):
    """All rows for declarations since `since`. Returns (rows, reported_count).

    Fails if the reported count changes between pages, if fewer or more rows
    arrive than reported, or if a gmProjectId repeats (a shifted page).
    """
    rows, reported, skip = [], None, 0
    while True:
        page, count = fetch_page(get, page_params(since, skip, page_size), sleep)
        if reported is None:
            reported = count
        elif count != reported:
            raise LoadError(f"source count changed during the load ({reported} -> {count}); retry later")
        rows.extend(page)
        skip += len(page)
        if len(page) < page_size or skip >= reported:
            break
    if len(rows) != reported:
        raise LoadError(f"fetched {len(rows)} rows but the source reported {reported}")
    ids = {r.get("gmProjectId") for r in rows}
    if len(ids) != len(rows):
        raise LoadError(f"{len(rows) - len(ids)} duplicate gmProjectId values across pages")
    return rows, reported


# ---------------------------------------------------------------------------
# Row conversion
# ---------------------------------------------------------------------------

def as_text(value):
    """Bronze keeps every field as a string: strings as-is, other JSON values as JSON text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def bronze_row(rec):
    unknown = set(rec) - set(SOURCE_FIELDS)
    if unknown:
        raise LoadError(f"source has new fields {sorted(unknown)}; review before loading")
    return tuple(as_text(rec.get(f)) for f in SOURCE_FIELDS)


def clean_title(title):
    """Control characters become spaces; capped at TITLE_MAX characters (D36)."""
    if title is None:
        return None
    cleaned = "".join(" " if (ord(c) < 32 or ord(c) == 127) else c for c in title)
    return cleaned[:TITLE_MAX]


def _digits(value):
    text = None if value is None else str(value).strip()
    return text if text and text.isdigit() else None


def geo_fields(county, state_code, county_code):
    """(state_fips, county_fips, geo_status, is_statewide).

    Statewide is decided by the county name only: Statewide rows carry
    non-zero county codes in the source. A missing county name or county code
    0 (for example Alaska REAAs) cannot be placed: UNMAPPABLE, no FIPS.
    """
    st = _digits(state_code)
    state_fips = st.zfill(2) if st and len(st) <= 2 else None
    if county == "Statewide":
        return state_fips, None, GEO_STATEWIDE, True
    cc = _digits(county_code)
    if not county or not state_fips or not cc or int(cc) == 0 or len(cc) > 3:
        return state_fips, None, GEO_UNMAPPABLE, False
    return state_fips, state_fips + cc.zfill(3), GEO_COUNTY, False


def parse_ts(text):
    if not text:
        return None
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def parse_amount(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def silver_row(rec, snapshot_date, load_id):
    state_fips, county_fips, geo_status, is_statewide = geo_fields(
        rec.get("county"), rec.get("stateNumberCode"), rec.get("countyCode"))
    declared = parse_ts(rec.get("declarationDate"))
    return (
        snapshot_date, load_id,
        int(rec["disasterNumber"]), declared.date() if declared else None, rec.get("incidentType"),
        int(rec["pwNumber"]), clean_title(rec.get("applicationTitle")), rec.get("applicantId"),
        rec.get("damageCategoryCode"), rec.get("damageCategoryDescrip"),
        rec.get("projectStatus"), rec.get("projectProcessStep"), rec.get("projectSize"),
        rec.get("stateAbbreviation"), state_fips, rec.get("county"),
        county_fips, geo_status, is_statewide,
        parse_amount(rec.get("projectAmount")), parse_ts(rec.get("lastRefresh")),
    )


# ---------------------------------------------------------------------------
# Gate and retention
# ---------------------------------------------------------------------------

def gate(rows, previous_rows, min_ratio):
    """(ok, reason). A snapshot may become latest only with rows > 0 and at
    least min_ratio of the previous SUCCEEDED snapshot's rows (D36)."""
    if rows <= 0:
        return False, "0 rows"
    if previous_rows and rows < min_ratio * previous_rows:
        return False, f"{rows} rows is below {min_ratio:.0%} of the previous snapshot's {previous_rows}"
    return True, "ok"


def expired_snapshots(dates, today, keep_days, protect=None):
    """Snapshot dates strictly older than today - keep_days, except `protect`
    (the newest SUCCEEDED snapshot, which is never deleted)."""
    cutoff = today - dt.timedelta(days=keep_days)
    return sorted(d for d in set(dates) if d < cutoff and d != protect)


# ---------------------------------------------------------------------------
# File export (D41)
# ---------------------------------------------------------------------------

def iso(value):
    """Dates as YYYY-MM-DD, timestamps as UTC ...Z, None as None."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def num(value):
    return None if value is None else float(value)


def dumps(obj):
    """Compact, ASCII-only JSON; NaN or Infinity is an error, never written."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True, allow_nan=False, sort_keys=False)


def build_exports(gold_rows, stats_rows, snapshot_date, load_id, since):
    """Per-disaster documents and the snapshot index from gold rows (dicts with
    the gold table's column names). Returns ({disaster_number: doc}, index)."""
    categories = {}
    for s in sorted(stats_rows, key=lambda r: (r["disaster_number"], r["damage_category_code"] or "")):
        categories.setdefault(s["disaster_number"], []).append({
            "code": s["damage_category_code"],
            "description": s.get("damage_category_descrip"),
            "recordCount": int(s["record_count"]),
            "mean": num(s["mean_amount"]),
            "stddev": num(s["stddev_amount"]),
            "totalAmount": num(s.get("total_amount")),
            "newestLastRefresh": iso(s.get("newest_last_refresh")),
        })
    by_disaster = {}
    for g in gold_rows:
        by_disaster.setdefault(g["disaster_number"], []).append(g)
    docs, index = {}, []
    for dn in sorted(by_disaster):
        rows = sorted(by_disaster[dn], key=lambda g: (g["pw_number"], g.get("applicant_id") or ""))
        states = sorted({g["state_abbreviation"] for g in rows if g.get("state_abbreviation")})
        declared = sorted({g["declaration_date"] for g in rows if g.get("declaration_date")})
        incidents = sorted({g["incident_type"] for g in rows if g.get("incident_type")})
        refreshed = [g["last_refresh"] for g in rows if g.get("last_refresh")]
        doc = {
            "schemaVersion": EXPORT_SCHEMA_VERSION,
            "snapshotDate": snapshot_date,
            "loadId": load_id,
            "source": {"dataset": ENTITY, "version": "v2", "declarationsSince": since},
            "disasterNumber": dn,
            "declarationDate": iso(declared[0]) if declared else None,
            "incidentTypes": incidents,
            "states": states,
            "newestLastRefresh": iso(max(refreshed)) if refreshed else None,
            "categories": categories.get(dn, []),
            "projects": [{
                "pw": g["pw_number"],
                "applicantId": g.get("applicant_id"),
                "title": g.get("application_title"),
                "category": g.get("damage_category_code"),
                "status": g.get("project_status"),
                "size": g.get("project_size"),
                "state": g.get("state_abbreviation"),
                "stateFips": g.get("state_fips"),
                "countyFips": g.get("county_fips"),
                "county": g.get("county_name"),
                "geo": g.get("geo_status"),
                "amount": num(g.get("project_amount")),
                "sigma": num(g.get("sigma")),
                "multipleOfMean": num(g.get("multiple_of_mean")),
            } for g in rows],
        }
        docs[dn] = doc
        index.append({
            "disasterNumber": dn,
            "declarationDate": doc["declarationDate"],
            "incidentTypes": incidents,
            "states": states,
            "projects": len(rows),
        })
    return docs, index


def build_manifest(previous, entry, remove_dates, since, generated_at):
    """New manifest: previous snapshots + `entry` (or None) - `remove_dates`.
    `latest` is the newest listed snapshot date."""
    snaps = {s["date"]: s for s in (previous or {}).get("snapshots", [])}
    if entry:
        snaps[entry["date"]] = entry
    for d in remove_dates:
        snaps.pop(d, None)
    ordered = sorted(snaps.values(), key=lambda s: s["date"], reverse=True)
    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "dataset": ENTITY,
        "declarationsSince": since,
        "generatedAt": generated_at,
        "latest": ordered[0]["date"] if ordered else None,
        "snapshots": ordered,
    }


def folder_dates(names):
    """Valid YYYY-MM-DD snapshot folder names as dates; anything else is ignored."""
    out = []
    for name in names:
        try:
            if len(name) == 10:
                out.append(dt.date.fromisoformat(name))
        except ValueError:
            pass
    return out


def write_text(path, text, atomic=False):
    """Write a file on the volume. With atomic=True, write a temp file and
    rename it over the target (falls back to a direct write if rename fails)."""
    if not atomic:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            os.remove(tmp)
        except OSError:
            pass


def read_manifest(root):
    try:
        with open(f"{root}/manifest.json", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def now_iso():
    return iso(dt.datetime.now(dt.timezone.utc))


def table(catalog, schema, name):
    for part in (catalog, schema, name):
        if not IDENTIFIER.fullmatch(part):
            raise ValueError(f"not a plain identifier: {part!r}")
    return f"`{catalog}`.`{schema}`.`{TABLE_PREFIX}{name}`"


# ---------------------------------------------------------------------------
# Spark part (job only)
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--catalog", default="users")
    p.add_argument("--schema", default="tom_jacobson")
    p.add_argument("--since", default="2021-01-01", type=dt.date.fromisoformat)
    p.add_argument("--keep-days", default=90, type=int)
    p.add_argument("--min-ratio", default=0.5, type=float)
    p.add_argument("--snapshot-date", default=None, type=dt.date.fromisoformat)
    p.add_argument("--volume", default=DEFAULT_VOLUME)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-declarations", action="store_true",
                   help="do not refresh declarations/v1 (FEMA declaration areas for the square image, D44)")
    args = p.parse_args(argv)
    if args.keep_days < 1 or not (0 < args.min_ratio <= 1):
        p.error("--keep-days must be >= 1 and --min-ratio in (0, 1]")
    for flag in ("catalog", "schema"):
        if not IDENTIFIER.fullmatch(getattr(args, flag)):
            p.error(f"--{flag} must contain only letters, digits and underscores")
    if not args.volume.startswith("/Volumes/") or args.volume.count("/") < 4:
        p.error("--volume must be a /Volumes/<catalog>/<schema>/<volume> path")
    args.volume = args.volume.rstrip("/")
    return args


def http_get(params):
    import requests
    resp = requests.get(API_URL, params=params, timeout=PAGE_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _schemas():
    from pyspark.sql import types as T
    kinds = {"string": T.StringType(), "int": T.IntegerType(), "date": T.DateType(),
             "boolean": T.BooleanType(), "decimal": T.DecimalType(18, 2), "timestamp": T.TimestampType()}
    bronze = T.StructType([T.StructField(f, T.StringType()) for f in SOURCE_FIELDS] + [
        T.StructField("snapshot_date", T.DateType()), T.StructField("load_id", T.StringType()),
        T.StructField("loaded_at", T.TimestampType())])
    silver = T.StructType([T.StructField(n, kinds[k]) for n, k in SILVER_COLUMNS])
    log = T.StructType([
        T.StructField("load_id", T.StringType()), T.StructField("snapshot_date", T.DateType()),
        T.StructField("status", T.StringType()), T.StructField("since_date", T.DateType()),
        T.StructField("source_count", T.LongType()), T.StructField("bronze_rows", T.LongType()),
        T.StructField("silver_rows", T.LongType()), T.StructField("stats_rows", T.LongType()),
        T.StructField("gold_rows", T.LongType()), T.StructField("previous_rows", T.LongType()),
        T.StructField("started_at", T.TimestampType()), T.StructField("finished_at", T.TimestampType()),
        T.StructField("message", T.StringType())])
    return bronze, silver, log


STATS_SQL = """
SELECT snapshot_date, load_id, disaster_number, damage_category_code,
       first(damage_category_descrip, true) AS damage_category_descrip,
       count(project_amount) AS record_count,
       avg(CAST(project_amount AS DOUBLE)) AS mean_amount,
       stddev_pop(CAST(project_amount AS DOUBLE)) AS stddev_amount,
       sum(project_amount) AS total_amount,
       max(last_refresh) AS newest_last_refresh
FROM {silver}
WHERE snapshot_date = DATE'{d}' AND load_id = '{lid}' AND project_amount IS NOT NULL
GROUP BY snapshot_date, load_id, disaster_number, damage_category_code
"""

GOLD_SQL = """
SELECT p.snapshot_date, p.load_id, p.disaster_number, p.declaration_date, p.incident_type,
       p.pw_number, p.applicant_id, p.application_title,
       p.damage_category_code, p.damage_category_descrip, p.project_status, p.project_size,
       p.state_abbreviation, p.state_fips, p.county_fips, p.county_name, p.geo_status, p.is_statewide,
       p.project_amount, s.record_count AS category_record_count,
       s.mean_amount AS category_mean, s.stddev_amount AS category_stddev,
       CASE WHEN p.project_amount IS NULL OR s.stddev_amount IS NULL OR s.stddev_amount < {zero} THEN NULL
            ELSE (CAST(p.project_amount AS DOUBLE) - s.mean_amount) / s.stddev_amount END AS sigma,
       CASE WHEN p.project_amount IS NULL OR s.mean_amount IS NULL OR s.mean_amount = 0 THEN NULL
            ELSE CAST(p.project_amount AS DOUBLE) / s.mean_amount END AS multiple_of_mean,
       p.last_refresh
FROM {silver} p
LEFT JOIN {stats} s
  ON s.snapshot_date = p.snapshot_date AND s.load_id = p.load_id
 AND s.disaster_number = p.disaster_number AND s.damage_category_code = p.damage_category_code
WHERE p.snapshot_date = DATE'{d}' AND p.load_id = '{lid}'
"""


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    started = dt.datetime.now(dt.timezone.utc)
    snap = args.snapshot_date or started.date()
    load_id = f"{snap.isoformat()}-{uuid.uuid4().hex[:8]}"
    print(f"load {load_id}: since {args.since}, keep {args.keep_days} days, dry_run={args.dry_run}")

    t0 = time.time()
    raw, reported = fetch_all(http_get, args.since)
    print(f"fetched {len(raw)} rows (source reported {reported}) in {time.time() - t0:.1f} s")
    bronze_rows = [bronze_row(r) for r in raw]
    silver_rows = [silver_row(r, snap, load_id) for r in raw]
    geo = {}
    for row in silver_rows:
        geo[row[17]] = geo.get(row[17], 0) + 1
    print(f"geo_status counts: {geo}")
    if args.dry_run:
        ok, reason = gate(len(silver_rows), None, args.min_ratio)
        print(f"dry run: gate {ok} ({reason}); nothing written")
        return 0 if ok else 1

    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    bronze_schema, silver_schema, log_schema = _schemas()
    t = {n: table(args.catalog, args.schema, n) for n in
         ("projects_bronze", "projects_silver", "category_stats_gold", "projects_gold", "load_log")}

    def ensure(name, schema, comment):
        if not spark.catalog.tableExists(t[name].replace("`", "")):
            spark.createDataFrame([], schema).write.format("delta").saveAsTable(t[name])
            spark.sql(f"COMMENT ON TABLE {t[name]} IS '{comment}'")

    ensure("load_log", log_schema, "OpenFEMA PA load log, one row per load (ops/openfema_load.py, BUILD_PLAN D36/D39). Latest snapshot = newest SUCCEEDED.")
    ensure("projects_bronze", bronze_schema, "Raw OpenFEMA PublicAssistanceFundedProjectsDetails v2 rows, all fields as strings, one snapshot per day (D36/D39).")
    ensure("projects_silver", silver_schema, "Typed, whitelisted OpenFEMA PA projects: cleaned titles, 5-digit county_fips, geo_status COUNTY/STATEWIDE/UNMAPPABLE (D36/D39).")

    def log_row(status, counts, message):
        return [(load_id, snap, status, args.since, reported, counts.get("bronze"), counts.get("silver"),
                 counts.get("stats"), counts.get("gold"), counts.get("previous"), started,
                 dt.datetime.now(dt.timezone.utc), message[:2000] if message else None)]

    prev = spark.sql(f"""SELECT silver_rows FROM {t['load_log']} WHERE status = 'SUCCEEDED'
                         AND snapshot_date < DATE'{snap}' ORDER BY snapshot_date DESC, finished_at DESC LIMIT 1""").collect()
    previous_rows = int(prev[0][0]) if prev else None
    counts = {"previous": previous_rows}
    # A same-day rerun first withdraws the day's earlier SUCCEEDED rows, so the
    # tool falls back to the previous day while this load is rewriting it.
    spark.sql(f"UPDATE {t['load_log']} SET status = 'SUPERSEDED' WHERE snapshot_date = DATE'{snap}' AND status = 'SUCCEEDED'")
    spark.createDataFrame(log_row("STARTED", counts, None), log_schema).write.format("delta").mode("append").saveAsTable(t["load_log"])

    def finish(status, message):
        spark.sql(f"DELETE FROM {t['load_log']} WHERE load_id = '{load_id}'")
        spark.createDataFrame(log_row(status, counts, message), log_schema).write.format("delta").mode("append").saveAsTable(t["load_log"])

    try:
        where = f"snapshot_date = DATE'{snap}'"
        loaded_at = dt.datetime.now(dt.timezone.utc)
        bdf = spark.createDataFrame([r + (snap, load_id, loaded_at) for r in bronze_rows], bronze_schema)
        bdf.write.format("delta").mode("overwrite").option("replaceWhere", where).saveAsTable(t["projects_bronze"])
        sdf = spark.createDataFrame(silver_rows, silver_schema)
        sdf.write.format("delta").mode("overwrite").option("replaceWhere", where).saveAsTable(t["projects_silver"])

        stats = spark.sql(STATS_SQL.format(silver=t["projects_silver"], d=snap, lid=load_id))
        if spark.catalog.tableExists(t["category_stats_gold"].replace("`", "")):
            stats.write.format("delta").mode("overwrite").option("replaceWhere", where).saveAsTable(t["category_stats_gold"])
        else:
            stats.write.format("delta").saveAsTable(t["category_stats_gold"])
            spark.sql(f"COMMENT ON TABLE {t['category_stats_gold']} IS 'Per snapshot, disaster, damage category: record_count, mean (avg), stddev (stddev_pop), null amounts excluded, as 2026h (D34/D36/D39).'")
        gold = spark.sql(GOLD_SQL.format(silver=t["projects_silver"], stats=t["category_stats_gold"],
                                         d=snap, lid=load_id, zero=ZERO_STDDEV))
        if spark.catalog.tableExists(t["projects_gold"].replace("`", "")):
            gold.write.format("delta").mode("overwrite").option("replaceWhere", where).saveAsTable(t["projects_gold"])
        else:
            gold.write.format("delta").saveAsTable(t["projects_gold"])
            spark.sql(f"COMMENT ON TABLE {t['projects_gold']} IS 'Per project and snapshot: category baseline, sigma (NULL when stddev is 0), multiple of the mean. Outliers are filtered by the tool at request time (D36/D39).'")

        def n(name):
            return spark.sql(f"SELECT count(*) FROM {t[name]} WHERE {where} AND load_id = '{load_id}'").collect()[0][0]
        counts.update(bronze=n("projects_bronze"), silver=n("projects_silver"),
                      stats=n("category_stats_gold"), gold=n("projects_gold"))
        print(f"written: {counts}")
        if not (counts["bronze"] == counts["silver"] == counts["gold"] == len(raw)):
            raise LoadError(f"row counts differ across layers: {counts}, fetched {len(raw)}")
        ok, reason = gate(counts["silver"], previous_rows, args.min_ratio)
        if not ok:
            finish("REJECTED", reason)
            print(f"REJECTED: {reason}")
            return 1
        export = export_snapshot(spark, t, snap, load_id, args, counts["gold"])
        print(f"exported: {export}")
    except Exception as err:
        finish("FAILED", f"{type(err).__name__}: {err}")
        raise

    finish("SUCCEEDED", f"{reported} rows; geo {geo}; files {export['disasters']} disasters, {export['bytes']} bytes")
    print(f"SUCCEEDED: snapshot {snap}")

    # Retention (D36, D41): old snapshots leave the manifest first, then their
    # table rows and folders are deleted. This snapshot is never deleted.
    snapshots_dir = f"{args.volume}/snapshots"
    dates = [r[0] for r in spark.sql(f"SELECT DISTINCT snapshot_date FROM {t['projects_silver']}").collect()]
    dates += folder_dates(os.listdir(snapshots_dir))
    expired = expired_snapshots(dates, started.date(), args.keep_days, protect=snap)
    manifest = build_manifest(read_manifest(args.volume), export["entry"], [d.isoformat() for d in expired],
                              args.since.isoformat(), now_iso())
    write_text(f"{args.volume}/manifest.json", dumps(manifest), atomic=True)
    print(f"manifest: latest {manifest['latest']}, {len(manifest['snapshots'])} snapshot(s)")
    for d in expired:
        for name in ("projects_bronze", "projects_silver", "category_stats_gold", "projects_gold"):
            spark.sql(f"DELETE FROM {t[name]} WHERE snapshot_date = DATE'{d}'")
        spark.sql(f"UPDATE {t['load_log']} SET status = 'EXPIRED' WHERE snapshot_date = DATE'{d}' AND status = 'SUCCEEDED'")
        folder = f"{snapshots_dir}/{d.isoformat()}"
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    print(f"retention: deleted snapshots {[d.isoformat() for d in expired]}")

    # D44: FEMA declaration areas for the square image, for the disasters of the
    # snapshot just committed. Runs last: a failure here fails the job run (so it
    # is noticed) but never touches the snapshot, which is already live.
    if not args.skip_declarations:
        declarations_module().run(args.volume)
    return 0


def declarations_module():
    here = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0] or "."))
    if not os.path.isfile(os.path.join(here, "declarations_load.py")):
        here = "/Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-beta/ops"
    if here not in sys.path:
        sys.path.insert(0, here)
    import declarations_load
    return declarations_load


def export_snapshot(spark, t, snap, load_id, args, gold_count):
    """Write snapshots/<date>/ for this load and check it (D41). The manifest is
    not updated here; a same-day rerun first takes the day out of it."""
    root, snap_iso = args.volume, snap.isoformat()
    previous = read_manifest(root)
    if previous and any(s.get("date") == snap_iso for s in previous.get("snapshots", [])):
        write_text(f"{root}/manifest.json",
                   dumps(build_manifest(previous, None, [snap_iso], args.since.isoformat(), now_iso())), atomic=True)
        print(f"manifest: withdrew {snap_iso} while it is rewritten")
    where = f"snapshot_date = DATE'{snap}' AND load_id = '{load_id}'"
    gold = [r.asDict() for r in spark.sql(f"SELECT * FROM {t['projects_gold']} WHERE {where}").collect()]
    stats = [r.asDict() for r in spark.sql(f"SELECT * FROM {t['category_stats_gold']} WHERE {where}").collect()]
    docs, index = build_exports(gold, stats, snap_iso, load_id, args.since.isoformat())

    day = f"{root}/snapshots/{snap_iso}"
    if os.path.isdir(day):
        shutil.rmtree(day)
    os.makedirs(f"{day}/disasters")
    total_bytes = 0
    for entry in index:
        text = dumps(docs[entry["disasterNumber"]])
        write_text(f"{day}/disasters/{entry['disasterNumber']}.json", text)
        entry["bytes"] = len(text.encode("utf-8"))
        total_bytes += entry["bytes"]
    write_text(f"{day}/index.json", dumps({"schemaVersion": EXPORT_SCHEMA_VERSION, "snapshotDate": snap_iso,
                                            "loadId": load_id, "disasters": index}))

    # Read every file back: one per disaster, and project totals equal gold.
    names = sorted(os.listdir(f"{day}/disasters"))
    projects = 0
    for name in names:
        with open(f"{day}/disasters/{name}", encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("snapshotDate") != snap_iso or doc.get("loadId") != load_id:
            raise LoadError(f"{name} belongs to another load")
        projects += len(doc["projects"])
    if len(names) != len(index) or projects != gold_count:
        raise LoadError(f"export check failed: {len(names)} files for {len(index)} disasters, "
                        f"{projects} projects for {gold_count} gold rows")
    entry = {"date": snap_iso, "loadId": load_id, "disasters": len(index), "projects": projects,
             "bytes": total_bytes, "generatedAt": now_iso()}
    return {"entry": entry, "disasters": len(index), "projects": projects, "bytes": total_bytes}


if __name__ == "__main__":
    code = main()
    if code:
        sys.exit(code)
