# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# DBTITLE 1,Cell 1
# MAGIC %md
# MAGIC # FEMA Evidence & Oversight Graph — Evaluation (live from OpenFEMA)
# MAGIC
# MAGIC **What this does:** pulls Public Assistance data straight from the public
# MAGIC OpenFEMA API (no table load, no API key), runs each of the three detection
# MAGIC tools' real logic, and checks every result against an **independent control**
# MAGIC computation. Prints a pass/fail result line and a JSON summary of the run.
# MAGIC
# MAGIC **How to use:** attach to any cluster, then **Run All**. Record the final
# MAGIC JSON summary in `eval/evaluation_documentation.md` under section 2,
# MAGIC "Measured: detection correctness (live OpenFEMA run)": run time, scope,
# MAGIC records pulled, and per-tool flagged/control/pass. Leave the acceptance
# MAGIC targets table as targets; this run does not measure those metrics.
# MAGIC
# MAGIC **Honest scope:** this measures *detection correctness* — does each tool
# MAGIC return the statistically correct set versus an independent method on the
# MAGIC same records. Tool-*selection* accuracy (can an agent pick the right tool
# MAGIC from plain language) is shown in the live demo, not here. Every output is a
# MAGIC review indicator on public aggregate data, not a finding.

# COMMAND ----------

# Config. STATE + since-year keep the pull small and the run fast.
STATE = "FL"
SINCE = "2021-01-01"
PAGE = 10000  # OpenFEMA per-call cap

import requests, statistics, json
from datetime import datetime

ENDPOINT = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"

def fetch_all(state, since):
    """Page the OpenFEMA API for one state since a date. Returns a list of dicts."""
    rows, skip = [], 0
    flt = f"stateAbbreviation eq '{state}' and declarationDate ge '{since}'"
    while True:
        params = {"$filter": flt, "$format": "jsona", "$top": PAGE, "$skip": skip,
                  "$orderby": "declarationDate"}
        r = requests.get(ENDPOINT, params=params, timeout=120)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        skip += PAGE
    return rows

print(f"Fetching {STATE} PA records since {SINCE} ...")
records = fetch_all(STATE, SINCE)
print(f"Pulled {len(records):,} records")

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 1 — get_cost_share_anomalies
# MAGIC Tool logic: flag ratio = federalShareObligated/totalObligated outside [0.70, 0.95],
# MAGIC for projects with totalObligated >= 100000. Control: independent recomputation.

# COMMAND ----------

MIN_TOTAL, LOW, HIGH = 100000.0, 0.70, 0.95

def tool_cost_share(recs):
    out = []
    for r in recs:
        total, fed = num(r.get("totalObligated")), num(r.get("federalShareObligated"))
        if not total or fed is None or total < MIN_TOTAL:
            continue
        ratio = fed / total
        if ratio < LOW or ratio > HIGH:
            out.append((r.get("pwNumber"), round(ratio, 4)))
    return out

def control_cost_share(recs):
    # Independent path: filter first, then ratio, using a comprehension.
    elig = [(r.get("pwNumber"),
             num(r.get("federalShareObligated")) / num(r.get("totalObligated")))
            for r in recs
            if num(r.get("totalObligated")) and num(r.get("totalObligated")) >= MIN_TOTAL
            and num(r.get("federalShareObligated")) is not None]
    return [(pw, round(ro, 4)) for pw, ro in elig if ro < LOW or ro > HIGH]

t1 = sorted(tool_cost_share(records))
c1 = sorted(control_cost_share(records))
t1_pass = (t1 == c1)
print(f"cost_share: tool flagged {len(t1)}, control {len(c1)}, match={t1_pass}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 2 — find_repeated_worksheets
# MAGIC Tool logic: group by (applicantId, applicationTitle, damageCategoryCode), flag count>=2.

# COMMAND ----------

from collections import defaultdict

def tool_repeated(recs, minc=2):
    g = defaultdict(int)
    for r in recs:
        key = (r.get("applicantId"), r.get("applicationTitle"), r.get("damageCategoryCode"))
        if all(k is not None for k in key):
            g[key] += 1
    return sorted(k for k, n in g.items() if n >= minc)

def control_repeated(recs, minc=2):
    seen = defaultdict(list)
    for i, r in enumerate(recs):
        key = (r.get("applicantId"), r.get("applicationTitle"), r.get("damageCategoryCode"))
        if None not in key:
            seen[key].append(i)
    return sorted(k for k, idxs in seen.items() if len(idxs) >= minc)

t2 = tool_repeated(records)
c2 = control_repeated(records)
t2_pass = (t2 == c2)
print(f"repeated_worksheets: tool {len(t2)} groups, control {len(c2)}, match={t2_pass}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 3 — detect_category_outliers
# MAGIC Tool logic: within a damage category, flag projectAmount >= mean + 3*stddev (population).

# COMMAND ----------

CAT, SIGMA = "C", 3.0

def cat_amounts(recs, cat):
    return [a for a in (num(r.get("projectAmount")) for r in recs
                        if r.get("damageCategoryCode") == cat) if a is not None]

def tool_outliers(recs, cat, sigma):
    amts = cat_amounts(recs, cat)
    if len(amts) < 2:
        return [], None, None
    mean, sd = statistics.fmean(amts), statistics.pstdev(amts)
    if sd <= 0:
        return [], mean, sd
    flagged = [r.get("pwNumber") for r in recs
               if r.get("damageCategoryCode") == cat
               and num(r.get("projectAmount")) is not None
               and (num(r.get("projectAmount")) - mean) / sd >= sigma]
    return sorted(flagged), mean, sd

def control_outliers(recs, cat, sigma):
    amts = cat_amounts(recs, cat)
    if len(amts) < 2:
        return []
    m = sum(amts) / len(amts)
    var = sum((x - m) ** 2 for x in amts) / len(amts)
    sd = var ** 0.5
    if sd <= 0:
        return []
    cut = m + sigma * sd
    return sorted(r.get("pwNumber") for r in recs
                  if r.get("damageCategoryCode") == cat
                  and num(r.get("projectAmount")) is not None
                  and num(r.get("projectAmount")) >= cut)

t3, mean3, sd3 = tool_outliers(records, CAT, SIGMA)
c3 = control_outliers(records, CAT, SIGMA)
t3_pass = (t3 == c3)
print(f"category_outliers (Cat {CAT}): tool {len(t3)}, control {len(c3)}, match={t3_pass}")

# COMMAND ----------

# DBTITLE 1,Cell 9
# MAGIC %md
# MAGIC ## Measured summary — JSON for the "Measured: detection correctness" section of evaluation_documentation.md

# COMMAND ----------

def total_fed(recs, state):
    return sum(num(r.get("federalShareObligated")) or 0.0
               for r in recs if r.get("stateAbbreviation") == state)

summary = {
    "run_at": datetime.utcnow().isoformat() + "Z",
    "state": STATE,
    "since": SINCE,
    "records_pulled": len(records),
    "state_total_federal_share_obligated": round(total_fed(records, STATE), 2),
    "tests": [
        {"tool": "get_cost_share_anomalies", "flagged": len(t1),
         "control": len(c1), "pass": t1_pass},
        {"tool": "find_repeated_worksheets", "flagged": len(t2),
         "control": len(c2), "pass": t2_pass},
        {"tool": "detect_category_outliers", "flagged": len(t3),
         "control": len(c3), "pass": t3_pass,
         "category": CAT, "category_mean": round(mean3, 2) if mean3 else None},
    ],
}
passed = sum(1 for t in summary["tests"] if t["pass"])
print(f"\n{'='*58}")
print(f"RESULT: {passed}/{len(summary['tests'])} detection tools matched their control")
print(f"{'='*58}")
print(json.dumps(summary, indent=2))
print("\nCopy the JSON above back to the assistant to fill the eval doc.")

# COMMAND ----------

# DBTITLE 1,Sync Word copy of eval doc
# MAGIC %md
# MAGIC ## Sync the Word copy of the eval doc
# MAGIC Regenerates `eval/evaluation_documentation.docx` from `eval/evaluation_documentation.md` so both copies match. Overwrites the existing .docx.

# COMMAND ----------

# DBTITLE 1,Install python-docx
# MAGIC %pip install -q python-docx

# COMMAND ----------

# DBTITLE 1,Convert markdown eval doc to docx
import re
from docx import Document

EVAL_DIR = "/Workspace/Users/phebe.arouni@hq.dhs.gov/2026-HACKATHON/eval"
MD_PATH = f"{EVAL_DIR}/evaluation_documentation.md"
DOCX_PATH = f"{EVAL_DIR}/evaluation_documentation.docx"

with open(MD_PATH, encoding="utf-8") as f:
    lines = f.read().splitlines()

doc = Document()


def add_inline(par, text):
    """Add text to a paragraph, rendering **bold** and `code` spans."""
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            par.add_run(part[1:-1]).font.name = "Consolas"
        else:
            par.add_run(part)


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


i = 0
while i < len(lines):
    line = lines[i]
    s = line.strip()
    if not s:
        i += 1
        continue
    m = re.match(r"^(#{1,6})\s+(.*)$", s)
    if m:
        doc.add_heading(m.group(2), level=len(m.group(1)))
        i += 1
        continue
    if s.startswith("|"):
        block = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            block.append(lines[i])
            i += 1
        rows = [split_row(r) for r in block
                if not re.match(r"^\|?\s*:?-{3,}", r.strip())]
        table = doc.add_table(rows=len(rows), cols=len(rows[0]))
        table.style = "Table Grid"
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                cell_par = table.cell(r_idx, c_idx).paragraphs[0]
                add_inline(cell_par, val)
                if r_idx == 0:
                    for run in cell_par.runs:
                        run.bold = True
        continue
    if re.match(r"^[-*]\s+", s):
        add_inline(doc.add_paragraph(style="List Bullet"), re.sub(r"^[-*]\s+", "", s))
        i += 1
        continue
    add_inline(doc.add_paragraph(), s)
    i += 1

doc.save(DOCX_PATH)

# Verify: reopen and report what was written.
chk = Document(DOCX_PATH)
headings = [p.text for p in chk.paragraphs if p.style.name.startswith("Heading")]
print(f"Wrote {DOCX_PATH}")
print(f"Paragraphs: {len(chk.paragraphs)}, tables: {len(chk.tables)}")
print("Headings:")
for h in headings:
    print("  -", h)
for t_idx, t in enumerate(chk.tables):
    print(f"Table {t_idx + 1}: {len(t.rows)} rows x {len(t.columns)} cols, header = {[c.text for c in t.rows[0].cells]}")