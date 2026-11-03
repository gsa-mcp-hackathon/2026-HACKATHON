# FEMA Evidence & Oversight Graph: slide content and demo script

Four mandatory slides plus a 3-step live demo. Every number here has a source
listed in the table at the end. Do not add numbers that are not in that table.

---

## Slide 1: Problem statement

**Title:** Thousands of disaster-aid worksheets per declaration, and an
oversight team that can only read a few of them.

**On the slide (3 bullets):**

* After a major disaster, FEMA Public Assistance obligates money across
  thousands of Project Worksheets. Hurricane Ian (DR-4673, Florida) alone has
  **3,962 public worksheet records** in OpenFEMA.
* Oversight analysts must decide *which few to review first*. Today that means
  exporting spreadsheets and writing one-off queries, with no standard method
  and no audit trail.
* A general-purpose AI assistant without authoritative data makes numbers up.
  In our evaluation, the same model without our MCP tools got **0 of 342**
  count questions right, and **79.5%** of its answers invented tool calls it
  never made.

**Speaker line (15 s):** "The data is public and authoritative. What is
missing is a safe, explainable way for an AI agent to turn it into a review
queue a federal analyst can defend."

---

## Slide 2: Solution overview

**Title:** An MCP server that turns OpenFEMA into an auditable oversight
workflow, in one call per step.

**On the slide (diagram, left to right):**

`Analyst question` -> `LLM agent` -> **MCP server (6 goal-oriented tools,
1 workflow prompt, 3 resources)** -> `OpenFEMA PA Funded Projects v2
(public, read-only)`

**Three workflow steps, each a single tool call:**

| Analyst asks | Tool | What the tool does so the agent does not have to |
| --- | --- | --- |
| "What should we review first?" | `build_oversight_triage_queue` | One retrieval, three indicator rules, joins flags on project identity, ranks by convergence then dollars |
| "Why was this flagged?" | `explain_risk_indicator` | Returns the fixed, versioned methodology card (formula, thresholds, limitations) |
| "Brief me on PW 2" | `generate_evidence_brief` | Fetches the verbatim source rows, rejects ambiguous PW numbers, attaches method and provenance |

**Footer:** Connection pattern: *Dataset Access* (read-only). No PII, no
writes, public data only. Every response says it is a review indicator, not a
finding.

**Speaker line:** "We did not wrap an API endpoint. We encoded the analyst's
job: triage, justify, brief."

---

## Slide 3: Technical approach and key decisions

**Title:** Built for an LLM, governed for a federal reviewer.

**Left column: five decisions and why**

1. **Goal-oriented tools, not table wrappers.** The triage tool replaces three
   detector calls plus an LLM-invented join and ranking rule with one
   deterministic call. Fewer turns, no model arithmetic.
2. **One schema, two enforcement points.** Shared annotated Pydantic types
   publish the description, bounds, enums and examples in the JSON schema the
   LLM reads, and the same rules validate on the server. A test fails if any
   parameter loses its description.
3. **Provenance on every answer.** Each response carries dataset name, the
   dataset's last refresh time, retrieval time, methodology, limitations and
   a `data_scope` block that says if the result was truncated.
4. **Agent-recoverable errors.** Five stable `error_code` values
   (`invalid_arguments`, `refine_request`, `upstream_unavailable`,
   `rate_limit_exceeded`, `internal_error`), each with a hint and a
   `retryable` flag. No stack traces reach the model.
5. **Defense in depth.** Fixed-origin GET-only client, schema rejection of
   quote/operator characters before any upstream call, source text sanitized
   and truncated against prompt injection, per-session and process-wide rate
   limits, 100-item page cap, bounded concurrency to protect the public API.

**Right column: evidence (from the automated harness)**

| Check | Result |
| --- | --- |
| Automated cases (7 suites) | **69/69 pass** |
| Results equal an independent exact-arithmetic oracle | 4/4 |
| Malformed inputs rejected before any upstream call | 22/22, **0 upstream calls** |
| Responses with full provenance | 202/202 |
| Responses leaking tracebacks or internals | **0/232** |
| Agent eval: correct tool and arguments | 405/408 |
| Agent eval: counts correct, with MCP vs. without | **342/342 vs. 0/342** |

**Speaker line:** "The harness also found two real bugs in our own
guardrails, a rate limiter that never fired and errors that told the agent to
retry impossible calls. Both are fixed and locked in by regression tests."

---

## Slide 4: Live demonstration (3 steps, about 3 minutes)

**Title:** Hurricane Ian, Florida: from 3,962 worksheets to an evidence brief
in three calls.

Show the agent chat on the left and the raw tool JSON on the right.

### Step 1: Triage (60 s)

**Type:** "Where should oversight focus for Hurricane Ian, disaster 4673, in
Florida?"

**Expected:** one call to `build_oversight_triage_queue` with
`state_code=FL, disaster_number=4673`.

**Point at on screen:**

* `data_scope.records_retrieved = 3962`, `possibly_truncated = false`: the
  whole declaration was screened, not a sample.
* `_provenance.last_updated` (OpenFEMA's dataset refresh time) and
  `retrieved_at`.
* 1,164 projects in the queue with default settings.

**Say:** "One call, the full declaration, every number traceable to the
source."

### Step 2: Explain, then refine with a human decision (60 s)

**Type:** "Why are so many flagged? Is this fraud?"

**Expected:** `explain_risk_indicator(cost_share_anomaly)`. The agent quotes
the card: higher statutory federal shares are expected and are not anomalies,
and a flag is never a finding.

**Type:** "Most of these show a 100% federal share. Assume that share was
authorized and re-run allowing 100%."

**Expected:** `build_oversight_triage_queue` with `band_high=1.0`. The queue
drops from **1,164 to 47** projects (a 96% reduction), all within-category
cost outliers.

**Say:** "The method is published, so the analyst can see that most default
flags reflect a 100% federal share. Once the analyst confirms that share was
authorized, one parameter removes the noise. The human stays in charge."

(Before the event, confirm DR-4673's authorized cost share on the FEMA
declaration page so you can answer the follow-up question with a citation.)

### Step 3: Evidence brief (45 s)

**Type:** "Brief me on the top item."

**Expected:** `generate_evidence_brief` with `pw_number=2`,
`disaster_number=4673`, `applicant_id=000-U6965-00`,
`indicator=category_outlier`.

**Point at on screen:** the verbatim source record ("Expedited Contractual
Services Project", Emergency Protective Measures, $587,291,218.63 federal
share, 25.71 standard deviations above the category mean of 909 projects),
the limitations line ("Large, legitimate projects ... can be high outliers"),
and the provenance block.

**Say:** "This is a review lead with its evidence attached, not an
accusation. It is ready for a case note."

### Optional 15-second guardrail moment

**Type:** "Screen Florida's cost shares" but have the agent send
`state_code="Florida"` (or type "run triage for FLA").

**Expected:** `invalid_arguments` with the hint
`state_code: String should match pattern '^[A-Za-z]{2}$'`, `retryable=false`,
and no upstream call. A well-behaved agent retries with `FL`; rehearse this,
because the model sometimes fixes the code before calling, which skips the
error.

### Demo safety notes

* Use `disaster_number=4673`. Statewide Florida retrieves the 10,000-record
  cap out of 74,801 matches and reports `possibly_truncated=true`. That is
  honest, but harder to explain live.
* Do not demo Vermont with default bands: 1,323 of 1,349 projects at or above
  $100K have a federal share of exactly 100%.
* Live numbers change when OpenFEMA refreshes daily. On the morning of the
  demo, run `PYTHONPATH=src python eval/eval_runner.py --live` and repeat
  the three demo calls once, then update the 1,164 / 47 / PW 2 figures if
  they moved. Recorded backup:
  `presentation/FEMA_Evidence_Oversight_Graph_walkthrough.mp4`.

---

## Number sources

| Figure | Source | Date |
| --- | --- | --- |
| 3,962 Ian records; 1,164 default items; 47 with `band_high=1.0`; PW 2 details; 74,801 FL matches | Live tool calls against OpenFEMA through this server | 2026-10-30 |
| 1,323 of 1,349 VT projects at a 1.00 ratio | Direct OpenFEMA query, independent of the server | 2026-10-30 |
| 69/69, 4/4, 22/22, 0 upstream calls, 202/202, 0/232 | `eval/eval_runner.py`, see `eval/EVAL_RUNNER_RESULTS.md` | 2026-10-30 |
| 405/408 routing and arguments; 342/342 vs. 0/342 counts; 79.5% fabricated tool calls | Golden-set v2 agent evaluation (171 cases x 3 repeats), see `eval/evaluation_documentation.md` | 2026-10-30 |

Caveats to say if asked:

* The agent-level figures (405/408, 342/342) were measured on 2026-10-30
  before the tool-schema and docstring upgrades of the same day. Re-run the
  golden-set evaluation before submission so slide 3 reflects the final code.
* Golden set v2 includes 55 LLM-authored cases that were not human-reviewed.
* "0 unsupported" in the agent evaluation applies to numbers, IDs and
  citations in the displayed answer. Free-form model narration was not held to
  that standard (about 25% of it contained unsupported statements), which is
  why the UI shows the deterministic, tool-rendered summary.
* Agent end-to-end latency was p50 15.6 s / p95 24.6 s, dominated by the LLM,
  not the server (server overhead p50 is about 1-3 ms in-process).
