"""Evaluation harness for the v1.1 MCP server.

Every check calls the real tools through an in-memory MCP client, exactly as an
agent would, and compares the result with something computed independently.

Suites
------
1. controls      Tool output vs. an independent SQLite implementation of each rule,
                 on the archived OpenFEMA snapshots of recorded run 20261102T152007Z,
                 and vs. the v1.0 tool output recorded in that run (regression parity).
2. errors        Invalid arguments, injection attempts, unknown records, and simulated
                 upstream failures must return isError with an actionable message.
3. contract      Exact tool set, read-only annotations, described inputs, output schemas.
4. stability     Each tool called repeatedly must return identical results; latency recorded.
5. live          (opt-in, --live) Current OpenFEMA data vs. an independent direct query.

Usage
-----
    python eval/run_evaluation.py --recorded-run-zip PATH_TO_SUBMISSION_ZIP \
        --output-dir eval/results/RUN_ID [--live]

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sqlite3
import statistics
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fema_oversight.data_access import OpenFEMASource, SnapshotSource  # noqa: E402
from fema_oversight.server import build_server  # noqa: E402

RECORDED_RUN = "20261102T152007Z"
SNAPSHOT_CASES = {
    # suite name: (snapshot file, tool, arguments, rule) -- same inputs as the v1.0 recorded run
    "cost_share": ("cost_share", "screen_cost_share_ratios", {"state_code": "FL", "disaster_number": 4734}),
    "repeated": ("repeated", "find_repeated_worksheet_groups", {"state_code": "FL", "disaster_number": 4673}),
    "category": (
        "category",
        "screen_category_cost_outliers",
        {"state_code": "FL", "disaster_number": 4673, "damage_category_code": "C"},
    ),
}


# ----------------------------------------------------------------- independent controls
def control_title_pattern(title: Any) -> str:
    """Re-implementation without regular expressions (independent of the server code)."""
    if not isinstance(title, str):
        return ""
    words, current = [], ""
    for ch in title.lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            current += ch
        elif current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    return " ".join(w for w in words if not w.isdigit())


def sqlite_control(rows: list[dict[str, Any]], rule: str) -> list[tuple]:
    """Compute each rule in SQL over the identical records."""
    conn = sqlite3.connect(":memory:")
    conn.create_function("sqrt", 1, math.sqrt)
    conn.create_function("pattern", 1, control_title_pattern)
    conn.execute(
        "CREATE TABLE pa (disaster INT, applicant TEXT, pw INT, title TEXT, category TEXT, "
        "amount REAL, total REAL, federal REAL)"
    )
    conn.executemany(
        "INSERT INTO pa VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                r.get("disasterNumber"),
                r.get("applicantId"),
                r.get("pwNumber"),
                r.get("applicationTitle"),
                r.get("damageCategoryCode"),
                r.get("projectAmount"),
                r.get("totalObligated"),
                r.get("federalShareObligated"),
            )
            for r in rows
        ],
    )
    sql = {
        "cost_share": "SELECT disaster, applicant, pw FROM pa WHERE total >= 100000 AND total > 0 AND "
        "federal IS NOT NULL AND (federal/total < 0.70 OR federal/total > 0.95)",
        "repeated": "SELECT disaster, applicant, pattern(title) AS p, category, COUNT(*) FROM pa WHERE "
        "disaster IS NOT NULL AND applicant IS NOT NULL AND category IS NOT NULL AND "
        "pattern(title) <> '' GROUP BY disaster, applicant, p, category HAVING COUNT(*) >= 2",
        "category": "WITH s AS (SELECT AVG(amount) m, sqrt(MAX(0, AVG(amount*amount) - AVG(amount)*AVG(amount))) sd "
        "FROM pa WHERE amount IS NOT NULL) SELECT disaster, applicant, pw FROM pa, s "
        "WHERE sd > 0 AND (amount - m) / sd >= 3",
    }[rule]
    result = sorted(conn.execute(sql).fetchall(), key=str)
    conn.close()
    return result


def tool_identities(rule: str, items: list[dict[str, Any]]) -> list[tuple]:
    if rule == "repeated":
        keys = [
            (
                g["disaster_number"],
                g["applicant_id"],
                g["title_pattern"],
                g["damage_category_code"],
                g["worksheet_count"],
            )
            for g in items
        ]
    else:
        keys = [(i["disaster_number"], i["applicant_id"], i["pw_number"]) for i in items]
    return sorted(keys, key=str)


# ----------------------------------------------------------------- MCP helpers
async def call(client: Client, tool: str, params: dict[str, Any]):
    start = time.perf_counter()
    result = await client.call_tool(tool, {"params": params}, raise_on_error=False)
    return result, time.perf_counter() - start


async def call_all_pages(client: Client, tool: str, params: dict[str, Any]) -> tuple[list[dict], dict]:
    """Follow next_offset until the last page; returns all items and the first page."""
    items, offset, first = [], 0, None
    list_key = "groups" if tool == "find_repeated_worksheet_groups" else "indicators"
    while offset is not None:
        result, _ = await call(client, tool, {**params, "limit": 100, "offset": offset})
        if result.is_error:
            raise RuntimeError(result.content[0].text)
        data = result.structured_content
        first = first or data
        items += data[list_key]
        offset = data["page"]["next_offset"]
    return items, first


def check(name: str, passed: bool, **detail: Any) -> dict[str, Any]:
    return {"name": name, "pass": bool(passed), **detail}


# ----------------------------------------------------------------- suites
async def suite_controls(recorded: zipfile.ZipFile, prefix: str) -> list[dict]:
    results = []
    for rule, (snapshot, tool, args) in SNAPSHOT_CASES.items():
        rows = json.loads(recorded.read(f"{prefix}snapshot_{snapshot}.json"))
        v10 = json.loads(recorded.read(f"{prefix}comparison_{snapshot}.json"))
        async with Client(build_server(SnapshotSource(rows))) as client:
            items, first = await call_all_pages(client, tool, args)
        actual = tool_identities(rule, items)
        expected = [tuple(row) for row in sqlite_control(rows, rule)]
        v10_actual = sorted((tuple(x[:5]) if rule == "repeated" else tuple(x)) for x in v10["actual"])
        v10_actual = sorted(v10_actual, key=str)
        results.append(
            check(
                f"control_{rule}",
                actual == expected and actual == v10_actual and not first["data_scope"]["possibly_truncated"],
                snapshot_rows=len(rows),
                tool_count=len(actual),
                sqlite_control_count=len(expected),
                v1_0_recorded_count=len(v10_actual),
                matches_sqlite=actual == expected,
                matches_v1_0=actual == v10_actual,
            )
        )
    return results


ERROR_CASES = [
    # (label, tool, params, substring expected in the error text)
    (
        "unknown damage category",
        "screen_category_cost_outliers",
        {"damage_category_code": "Z", "state_code": "FL"},
        "damage_category_code",
    ),
    ("missing scope", "screen_category_cost_outliers", {"damage_category_code": "C"}, "provide state_code"),
    (
        "sigma out of range",
        "screen_category_cost_outliers",
        {"damage_category_code": "C", "state_code": "FL", "sigma_threshold": 50},
        "sigma_threshold",
    ),
    ("three-letter state", "screen_cost_share_ratios", {"state_code": "FLA"}, "state_code"),
    ("OData injection in state", "screen_cost_share_ratios", {"state_code": "F' or 1 eq 1"}, "state_code"),
    ("inverted band", "screen_cost_share_ratios", {"state_code": "FL", "band_low": 0.9, "band_high": 0.5}, "band_low"),
    ("ratio above 1", "screen_cost_share_ratios", {"state_code": "FL", "band_high": 1.5}, "band_high"),
    (
        "repeat count 1",
        "find_repeated_worksheet_groups",
        {"state_code": "FL", "min_repeat_count": 1},
        "min_repeat_count",
    ),
    ("misspelled argument", "find_repeated_worksheet_groups", {"state_code": "FL", "min_repeats": 3}, "Extra inputs"),
    ("negative offset", "find_repeated_worksheet_groups", {"state_code": "FL", "offset": -1}, "offset"),
    ("queue without disaster", "build_review_queue", {"state_code": "FL"}, "disaster_number"),
    ("unknown indicator", "explain_review_indicator", {"indicator": "fraud_score"}, "indicator"),
    (
        "OData injection in applicant",
        "prepare_evidence_brief",
        {"pw_number": 4902, "disaster_number": 4673, "indicator": "category_outlier", "applicant_id": "x' or 1 eq 1"},
        "applicant_id",
    ),
    (
        "worksheet not found",
        "prepare_evidence_brief",
        {"pw_number": 999999, "disaster_number": 4673, "indicator": "category_outlier"},
        "[NOT_FOUND]",
    ),
    (
        "category with no data",
        "screen_category_cost_outliers",
        {"damage_category_code": "C", "state_code": "TX", "disaster_number": 4673},
        "[INSUFFICIENT_DATA]",
    ),
]

UPSTREAM_CASES = [
    ("HTTP 503", lambda r: httpx.Response(503), "[UPSTREAM_UNAVAILABLE]", "Retryable: yes"),
    ("HTTP 429", lambda r: httpx.Response(429), "[UPSTREAM_UNAVAILABLE]", "Retryable: yes"),
    ("invalid JSON", lambda r: httpx.Response(200, content=b"<html>"), "[UPSTREAM_INVALID_RESPONSE]", "Retryable"),
    (
        "missing record list",
        lambda r: httpx.Response(200, json={"metadata": {}}),
        "[UPSTREAM_INVALID_RESPONSE]",
        "Retryable",
    ),
]


async def suite_errors(rows: list[dict]) -> list[dict]:
    results = []
    async with Client(build_server(SnapshotSource(rows))) as client:
        for label, tool, params, expected in ERROR_CASES:
            result, _ = await call(client, tool, params)
            text = result.content[0].text if result.content else ""
            results.append(
                check(
                    f"error: {label}",
                    result.is_error and expected in text and "Traceback" not in text,
                    tool=tool,
                    response=text[:300],
                )
            )
    for label, handler, code, retry in UPSTREAM_CASES:
        server = build_server(OpenFEMASource(transport=httpx.MockTransport(handler)))
        async with Client(server) as client:
            result, _ = await call(client, "screen_cost_share_ratios", {"state_code": "FL"})
        text = result.content[0].text if result.content else ""
        ok = result.is_error and text.startswith(code) and retry in text and "fema.gov" not in text
        results.append(check(f"upstream: {label}", ok, response=text[:300]))
    return results


async def suite_contract(rows: list[dict]) -> list[dict]:
    async with Client(build_server(SnapshotSource(rows))) as client:
        tools = await client.list_tools()
    names = sorted(t.name for t in tools)
    undocumented = []
    for tool in tools:
        defs = tool.inputSchema.get("$defs", {})
        ref = tool.inputSchema["properties"]["params"].get("$ref", "")
        model = defs.get(ref.split("/")[-1], tool.inputSchema["properties"]["params"])
        for field, spec in model["properties"].items():
            if not (spec.get("description") or any("description" in s for s in spec.get("anyOf", []))):
                undocumented.append(f"{tool.name}.{field}")
    return [
        check(
            "contract: exact tool set",
            names
            == sorted(
                [
                    "build_review_queue",
                    "explain_review_indicator",
                    "find_repeated_worksheet_groups",
                    "prepare_evidence_brief",
                    "screen_category_cost_outliers",
                    "screen_cost_share_ratios",
                ]
            ),
            tools=names,
        ),
        check(
            "contract: all tools read-only",
            all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in tools),
        ),
        check(
            "contract: USE WHEN / DO NOT USE in every description",
            all("USE WHEN" in t.description and "DO NOT USE" in t.description for t in tools),
        ),
        check("contract: every input field described", not undocumented, undocumented=undocumented),
        check("contract: every tool has an output schema", all(t.outputSchema for t in tools)),
    ]


STABILITY_CALLS = [
    ("screen_category_cost_outliers", {"state_code": "FL", "disaster_number": 4673, "damage_category_code": "C"}),
    ("find_repeated_worksheet_groups", {"state_code": "FL", "disaster_number": 4673}),
    ("screen_cost_share_ratios", {"state_code": "FL", "disaster_number": 4734}),
    ("build_review_queue", {"state_code": "FL", "disaster_number": 4673}),
    ("prepare_evidence_brief", {"pw_number": 4902, "disaster_number": 4673, "indicator": "category_outlier"}),
    ("explain_review_indicator", {"indicator": "repeated_worksheet"}),
]


def _without_timestamps(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_timestamps(v) for k, v in value.items() if k != "retrieved_at"}
    if isinstance(value, list):
        return [_without_timestamps(v) for v in value]
    return value


async def suite_stability(rows: list[dict], repeats: int) -> tuple[list[dict], dict]:
    results, latency = [], {}
    async with Client(build_server(SnapshotSource(rows))) as client:
        for tool, params in STABILITY_CALLS:
            outputs, times = [], []
            for _ in range(repeats):
                result, seconds = await call(client, tool, params)
                outputs.append(json.dumps(_without_timestamps(result.structured_content), sort_keys=True))
                times.append(seconds)
            latency[tool] = {
                "p50_ms": round(statistics.median(times) * 1000, 1),
                "max_ms": round(max(times) * 1000, 1),
                "calls": repeats,
            }
            results.append(check(f"stable: {tool}", len(set(outputs)) == 1, repeats=repeats))
    return results, latency


async def independent_live_rows(odata_filter: str, fields: str) -> list[dict]:
    """Direct OpenFEMA query written without any server code."""
    url = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url, params={"$filter": odata_filter, "$select": fields, "$top": 10000})
        response.raise_for_status()
        return response.json()["PublicAssistanceFundedProjectsDetails"]


async def suite_live() -> tuple[list[dict], dict]:
    results, latency = [], {}
    fields = (
        "disasterNumber,applicantId,pwNumber,applicationTitle,damageCategoryCode,projectAmount,totalObligated,"
        "federalShareObligated"
    )
    async with Client(build_server()) as client:
        start = time.perf_counter()
        items, first = await call_all_pages(
            client,
            "screen_category_cost_outliers",
            {"state_code": "LA", "disaster_number": 4611, "damage_category_code": "F"},
        )
        latency["screen_category_cost_outliers LA-4611-F"] = round(time.perf_counter() - start, 2)
        rows = await independent_live_rows(
            "disasterNumber eq 4611 and damageCategoryCode eq 'F' and stateAbbreviation eq 'LA'", fields
        )
        expected = [tuple(r) for r in sqlite_control(rows, "category")]
        results.append(
            check(
                "live: LA DR-4611 Cat F outliers vs direct query",
                tool_identities("category", items) == expected,
                records=first["data_scope"]["records_retrieved"],
                control_records=len(rows),
                pw_numbers=[i["pw_number"] for i in items],
                sigma=[i["sigma_above_mean"] for i in items],
            )
        )

        start = time.perf_counter()
        groups, first = await call_all_pages(
            client, "find_repeated_worksheet_groups", {"state_code": "NC", "disaster_number": 4827}
        )
        latency["find_repeated_worksheet_groups NC-4827"] = round(time.perf_counter() - start, 2)
        rows = await independent_live_rows("disasterNumber eq 4827 and stateAbbreviation eq 'NC'", fields)
        expected = [tuple(r) for r in sqlite_control(rows, "repeated")]
        results.append(
            check(
                "live: NC DR-4827 repeated groups vs direct query",
                tool_identities("repeated", groups) == expected,
                groups=len(groups),
                control_groups=len(expected),
                same_wording=sum(g["match_type"] == "same_wording" for g in groups),
                records=first["data_scope"]["records_retrieved"],
            )
        )

        start = time.perf_counter()
        brief, _ = await call(
            client,
            "prepare_evidence_brief",
            {
                "pw_number": 1725,
                "disaster_number": 4611,
                "indicator": "category_outlier",
                "applicant_id": "109-99109-00",
            },
        )
        latency["prepare_evidence_brief PW1725"] = round(time.perf_counter() - start, 2)
        data = brief.structured_content or {}
        results.append(
            check(
                "live: evidence brief PW 1725 re-checks indicator",
                not brief.is_error and data.get("indicator_check", {}).get("indicator_met") is True,
                indicator_check=data.get("indicator_check"),
                title=(data.get("source_records") or [{}])[0].get("application_title"),
            )
        )

        start = time.perf_counter()
        queue, _ = await call(client, "build_review_queue", {"state_code": "LA", "disaster_number": 4611, "limit": 5})
        latency["build_review_queue LA-4611"] = round(time.perf_counter() - start, 2)
        data = queue.structured_content or {}
        results.append(
            check(
                "live: review queue LA DR-4611 builds",
                not queue.is_error and bool(data.get("queue")),
                top=[(e["pw_number"], e["indicator_count"]) for e in data.get("queue", [])],
                indicator_totals=data.get("indicator_totals"),
                records=data.get("data_scope", {}).get("records_retrieved"),
                possibly_truncated=data.get("data_scope", {}).get("possibly_truncated"),
            )
        )
    return results, latency


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src").rglob("*.py")):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def write_report(out: Path, summary: dict) -> None:
    lines = [
        f"# Evaluation report, run {summary['run_id']}",
        "",
        f"* Server version: {summary['server_version']}",
        f"* Source fingerprint (SHA-256 of src/**/*.py): `{summary['source_sha256']}`",
        f"* Snapshots: recorded run {RECORDED_RUN}",
        f"* Result: {summary['passed']} of {summary['total']} checks passed",
        "",
        "| Suite | Check | Result | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for suite, checks in summary["suites"].items():
        for c in checks:
            detail = {k: v for k, v in c.items() if k not in {"name", "pass", "response"}}
            text = json.dumps(detail)[:160].replace("|", "/") if detail else c.get("response", "")[:120]
            lines.append(f"| {suite} | {c['name']} | {'PASS' if c['pass'] else 'FAIL'} | {text} |")
    lines += [
        "",
        "Latency (in-process MCP calls on snapshots, ms; live calls in seconds):",
        "",
        "```",
        json.dumps(summary["latency"], indent=2),
        "```",
        "",
    ]
    (out / "EVALUATION_REPORT.md").write_text("\n".join(lines))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recorded-run-zip", type=Path, default=ROOT / "eval/fixtures/openfema-20261102.zip")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    from fema_oversight import __version__

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.output_dir or ROOT / "eval" / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.recorded_run_zip) as recorded:
        prefix = next(n for n in recorded.namelist() if n.endswith(f"{RECORDED_RUN}/summary.json"))[:-12]
        controls = await suite_controls(recorded, prefix)
        rows = []
        for name in ("category", "cost_share", "repeated"):
            rows += json.loads(recorded.read(f"{prefix}snapshot_{name}.json"))
    # The category and repeated snapshots overlap; serve each worksheet row once.
    unique = list({json.dumps(r, sort_keys=True): r for r in rows}.values())
    suites = {"controls": controls, "errors": await suite_errors(unique), "contract": await suite_contract(unique)}
    suites["stability"], latency = await suite_stability(unique, args.repeats)
    live_incomplete = False
    if args.live:
        try:
            suites["live"], live_latency = await suite_live()
            latency["live_seconds"] = live_latency
        except (RuntimeError, httpx.HTTPError) as exc:
            # Preserve the completed offline evidence when an upstream request fails.
            # One failed completion check represents an incomplete suite, not four executed checks.
            live_incomplete = True
            suites["live"] = [check("live suite completed", False, error_type=type(exc).__name__)]
    total = sum(len(c) for c in suites.values())
    passed = sum(c["pass"] for checks in suites.values() for c in checks)
    summary = {
        "run_id": run_id,
        "server_version": __version__,
        "source_sha256": source_fingerprint(),
        "recorded_snapshots": RECORDED_RUN,
        "passed": passed,
        "total": total,
        "all_pass": passed == total,
        "live_requested": args.live,
        "live_incomplete": live_incomplete,
        "suites": suites,
        "latency": latency,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    write_report(out, summary)
    print(f"{passed}/{total} checks passed -> {out}")
    for checks in suites.values():
        for c in checks:
            if not c["pass"]:
                print("FAIL", json.dumps(c)[:400])
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
