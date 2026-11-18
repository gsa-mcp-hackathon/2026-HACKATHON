# FEMA Evidence & Oversight Graph

**Trusted oversight infrastructure for AI agents using evidence-backed review recommendations.**

GSA MCP Server & AI Agent Government Hackathon | Dataset Access track | Phebe Arouni & Tom Jacobson | Final package, November 4, 2026

Evidence of record: recorded run `20261102T152007Z` (Python source SHA-256 `9cdad51ec7870e12d2fff37a2b570a5030835a5b799f542b8560f6224990ea94`, MLflow run `ff6c41f62dc04e2c929fea1e08ba3e21`, experiment `1305734463288268`), plus re-verification on November 4, 2026 at 06:53 UTC against live OpenFEMA data.

November 18, 2026 update: a v1.1 candidate MCP server, with its own recorded evaluation, is in `SUBMISSION_FINAL/mcp_server_v1_1/` (run `20261118T094257Z`, source SHA-256 `6dee75f765962a954ca75ca7cb5884d5f198f48eac87d3408fa7cff78386dd98`). Section 0 maps it to the three judging criteria. The deployed app and the v1.0 evidence above are unchanged.

---

## 0. v1.1 Candidate Against the Judging Criteria

The v1.1 tree combines the tested v1.0 tools (the code the live app runs) with the strongest parts of the October 30 repository line: a separate data client, one methodology module, a cross-indicator review queue, and structured errors. We rebuilt it around the three criteria. It does not replace the recorded v1.0 run. It has its own tests and its own recorded run.

### Criterion 1: Code readability and maintainability

| Module | Single responsibility | Depends on |
| --- | --- | --- |
| `schemas/inputs.py` | Pydantic request model per tool: validated, described, `extra="forbid"` | nothing internal |
| `schemas/outputs.py` | Pydantic result models; published as each tool's `outputSchema` | inputs (enums) |
| `data_access.py` | `PAQuery` (what to fetch), `OpenFEMASource` (hardened HTTP), `SnapshotSource` (archived data) | errors |
| `indicators.py` | The three review rules as pure functions; no I/O, MCP, or HTTP | `to_number` only |
| `methodology.py` | Methodology cards, caveat, limitations, provenance builder: one source of truth for what each rule means | schemas |
| `errors.py` | `ReviewToolError` with stable codes and a fixed message shape | nothing |
| `tools/screening.py`, `tools/review.py` | Agent-facing actions: `run_*` logic plus `register()` | all of the above |
| `server.py` | `build_server(source)`: the only place components are wired together | tools, methodology |

Dependencies run one way, so you can read and test any rule without MCP or a network. Comments and docstrings explain why the code does something (for example, why `pwNumber` alone is not an identity, or why the snapshot source exists). Lint and format checks are clean (ruff, 120 columns).

### Criterion 2: Server performance and reliability (evaluation setup and results)

Harness: `eval/run_evaluation.py`. Every check calls the real tools through an in-memory MCP client, the same way an agent does, and compares the result with something computed independently. Run `20261118T094257Z`: 37 of 37 checks passed. Separately, 63 of 63 unit and contract tests passed.

| Suite | Inputs | Result |
| --- | --- | --- |
| Controls | Archived OpenFEMA snapshots from run 20261102T152007Z: FL DR-4734 cost share (238 rows), FL DR-4673 repeats (3,964 rows), FL DR-4673 Category C (179 rows). Compared with an independent SQLite implementation and with the v1.0 recorded tool output | 3/3 exact matches: 238 = 238 = 238; 74 = 74 = 74; 3 = 3 = 3 |
| Error handling | 15 bad-argument cases (unknown category, out-of-range sigma, inverted band, OData injection in state and applicant, misspelled argument, unknown record, empty baseline) plus 4 simulated upstream failures (503, 429, invalid JSON, missing record list) | 19/19 return `isError` with the field named or a coded message `[CODE] ... Hint: ... Retryable: yes/no`; no stack trace or upstream URL leaked |
| Contract | Tool list and schemas | 5/5: exact tool set, all read-only, USE WHEN / DO NOT USE in every description, every input field described, output schema on every tool |
| Stability | 10 identical calls per tool | 6/6 tools returned identical results (timestamps excluded); in-process p50 6-81 ms |
| Live | Current OpenFEMA vs. a direct query written independently of the server | 4/4: LA DR-4611 Cat F gives 115 records and PWs 1725 / 1679 / 5757 at 7.73 / 4.75 / 3.29 sigma; NC DR-4827 gives 86 = 86 groups (2 same-wording); evidence brief PW 1725 (Houma Power Plant) re-check met; review queue LA DR-4611 built from 3,648 records, not truncated; live calls 0.44-0.79 s |

Negative check: when one snapshot amount was changed to $1e9, the control comparison reported a mismatch, so a passing control means something. Results are in `eval/results/20261118T094257Z/EVALUATION_REPORT.md`, and `summary.json` is in the volume `hackathon_submissions/20261118_v1_1_eval/`.

### Criterion 3: Adherence to MCP design principles

* Pydantic inputs: each tool takes one validated request model. Invalid input is rejected before any tool code runs, and the error names the field, for example `params.applicant_id String should match pattern ...`.
* Typed outputs: every tool publishes an `outputSchema` and returns `structuredContent` with shared `provenance`, `data_scope` (count, cap, `possibly_truncated`), and `page` blocks.
* Descriptions written for the model: every description says what the tool does, USE WHEN, DO NOT USE (naming the sibling tool to use instead), the required scope, and how to read the result. Server `instructions` give the routing order.
* Tools built around goals, not endpoints. All six tools read the same single OpenFEMA endpoint, so the tools are defined by analyst questions:

| Tool | Analyst goal | What it does beyond one REST call |
| --- | --- | --- |
| `build_review_queue` | Where do I start in this disaster? | One retrieval, all three rules (category outliers for every category), merged by worksheet identity, ranked, every reason listed |
| `screen_category_cost_outliers` | Which projects cost far more than similar work? | Builds the baseline, computes sigma, ranks, records scope |
| `find_repeated_worksheet_groups` | Is the same project listed more than once? | Normalizes titles, groups, labels each group same_wording or numbered_series, puts closest matches first |
| `screen_cost_share_ratios` | Which federal shares fall outside the band? | Computes ratios, marks below or above the band, states the authorization limit |
| `prepare_evidence_brief` | Give me the evidence package for this worksheet | Resolves identity (reports ambiguity), re-runs the triggering rule against fresh peers, adds the method card and next review steps |
| `explain_review_indicator` | How was this produced, and what can't it tell me? | Returns the same card the tools execute against; makes no network call |

* Safety: every tool has `readOnlyHint: true`, `destructiveHint: false`, and `idempotentHint: true`. There are no write, approve, or disposition tools. `mask_error_details=True` hides internal exceptions.
* Resources `fema-pa://provenance` and `fema-pa://methodology`, and the prompt `disaster_review(state_code, disaster_number)`.

Name changes from v1.0: `detect_category_outliers` -> `screen_category_cost_outliers`, `find_repeated_worksheets` -> `find_repeated_worksheet_groups`, `get_cost_share_anomalies` -> `screen_cost_share_ratios`, `explain_risk_indicator` -> `explain_review_indicator`, `generate_evidence_brief` -> `prepare_evidence_brief`. New: `build_review_queue`.

What v1.1 has not done yet: the model-in-the-loop measurements (first-tool selection 15/15, golden sets, with-tools vs. no-tools 15/15 vs. 0/15) were recorded on v1.0 names and descriptions and have not been re-run on v1.1. The analyst web page and bounded agent loop stay in the deployed v1.0 app and are not part of the v1.1 tree. v1.1 is not deployed.

---

## Contents

0. v1.1 Candidate Against the Judging Criteria
1. Executive Summary
2. Winning Elevator Pitch
3. Final Problem Statement
4. Final Solution Statement
5. Final Architecture
6. Directed Agent Graph
7. MCP Tool Definitions
8. Tool Descriptions (agent-facing text)
9. Demo Script (live, under 2 minutes)
10. Evaluation Plan
11. Testing Methodology
12. Metrics and Results
13. Security Controls
14. Governance Controls
15. Explainability Framework
16. Evidence Chain Framework
17. Presentation Storyline
18. Complete Replacement Slide Deck (with speaker notes)
19. Judge Q&A Responses
20. Competitive Positioning
21. Risks and Mitigations
22. Lessons Learned
23. Future Roadmap
24. Final Closing Statement

Appendix A. FEMA terminology standard
Appendix B. Claims register (every number in this package and where it comes from)

---

## 1. Executive Summary

FEMA Public Assistance (PA) obligates billions of dollars after every major disaster through tens of thousands of Project Worksheets. Oversight teams in FEMA, DHS OIG, and state recipient offices must decide where to look first, but they cannot review every worksheet, and they cannot accept an AI answer they cannot trace back to a federal record.

The FEMA Evidence & Oversight Graph is trusted oversight infrastructure for AI agents. It is a Model Context Protocol (MCP) server, hosted as an authenticated Databricks App, that gives any MCP-capable agent five read-only tools over OpenFEMA Public Assistance Funded Projects Details (v2). Every tool response carries its own evidence: the source dataset, retrieval timestamp, the exact rule and parameters executed, the record count and retrieval cap, and the limitations that apply. The result is a review recommendation an analyst can verify in minutes, not a conclusion an analyst has to take on faith.

Three design decisions make it trustworthy:

* **Deterministic evidence, not model arithmetic.** The model chooses which tool to call and with what parameters. All counts, statistics, and identifiers are computed by the tools. The answer shown to the analyst is rendered from structured tool output, never from free model prose.
* **Every answer carries its evidence chain.** Source, provenance, methodology, limitations, timestamp, and the disaster / applicant / Project Worksheet identity of each record travel with the result.
* **AI recommends review; people decide.** The system has no write, approve, or disposition tools. Every output is labeled a review indicator that requires analyst review.

Measured results (recorded run `20261102T152007Z`, Databricks, Python 3.12.3):

| What we measured | Result |
| --- | --- |
| Automated tests | 71 of 71 passed; lint clean |
| Tool output vs. independent SQLite control on identical OpenFEMA snapshots | 3 of 3 exact matches (238, 74, 3) |
| Correct first tool chosen by the model | 15 of 15 questions |
| Exact-count questions answered correctly: with tools vs. same model without tools | 15 of 15 vs. 0 of 15 |
| Median tool latency including live OpenFEMA retrieval | 0.36 to 0.46 seconds |
| Unsupported numbers or identifiers in displayed answers (golden set v2, 513 answers) | 0 |
| Unsupported statements in free model prose on the same cases | about 25%, which is why free prose is never displayed |

The last two rows are the core of the submission. We measured the model writing unsupported statements, and we designed the system so that those statements never reach an analyst.

---

## 2. Winning Elevator Pitch

After a disaster, FEMA oversight teams face tens of thousands of Public Assistance worksheets and a simple question: where should a person look first? AI can help, but only if every answer can be traced to a federal record.

We built the FEMA Evidence & Oversight Graph: trusted oversight infrastructure for AI agents using evidence-backed review recommendations. Any MCP agent can ask it a question. It retrieves OpenFEMA records, applies a documented rule, and returns a review recommendation with the source records, the method, the limits, and a timestamp. The model never does the math and never draws the conclusion. An analyst does.

We tested it the way an Inspector General would. Every tool result matched an independent calculation. The model chose the right tool 15 out of 15 times. With our tools it answered exact-count questions correctly 15 of 15 times; without them, 0 of 15. When we caught the model writing unsupported prose, we removed model prose from the answer entirely.

It runs on Databricks today, and the same pattern applies to any federal open dataset.

---

## 3. Final Problem Statement

FEMA Public Assistance oversight is a prioritization problem under an evidence standard.

* **Volume.** Large declarations generate thousands of Project Worksheets. Hurricane Ida (DR-4611-LA) alone has 115 public Category F (Public Utilities) records in OpenFEMA. Tropical Storm Helene (DR-4827-NC) has applicants with dozens of similarly titled worksheets. Analysts cannot read every record.
* **Evidence standard.** Oversight work products must trace to source records and documented criteria. An AI answer that cannot show its source, its rule, and its limits cannot be used in an oversight workflow, however fluent it is.
* **Measured model behavior.** Without data access, the same model we use answered 0 of 15 exact-count questions correctly. With data access but free narration, about one quarter of its prose statements were unsupported by the tool evidence it had just received.
* **Gap.** Existing options either give analysts raw data with no prioritization, or give them fluent AI text with no evidence chain. Neither meets an oversight evidence standard.

Problem statement: *Oversight analysts need a way to let AI agents prioritize Public Assistance records for human review while guaranteeing that every recommendation is traceable to federal source records, a documented method, and stated limitations.*

---

## 4. Final Solution Statement

The FEMA Evidence & Oversight Graph is a read-only MCP server that turns OpenFEMA Public Assistance records into evidence-backed review recommendations for AI agents and the analysts who supervise them.

* **For agents:** five narrowly scoped tools with typed parameters, explicit use/do-not-use guidance, read-only annotations, and structured outputs, plus a provenance resource and a review prompt.
* **For analysts:** a review recommendation that states what was screened, which records were returned and why, how the number was calculated, what the method cannot tell you, and when the data was retrieved.
* **For oversight leaders:** a documented methodology, recorded test runs with source fingerprints, independent control comparisons, and a hard boundary: the system recommends review; analysts make determinations.
* **For other agencies:** a reusable pattern (deterministic tool evidence + evidence chain + deterministic rendering + human review gate) that applies to any federal open dataset.

---

## 5. Final Architecture

```
                      Analyst (browser)            Any MCP client (agent)
                             |                               |
              Databricks Apps OAuth (unauthenticated -> 302 redirect)
                             |                               |
                 +-----------v------------+       +----------v-----------+
                 |  Analyst review page   |       |   /mcp endpoint      |
                 |  same-origin guard     |       |   (FastMCP, HTTP)    |
                 |  (403 otherwise)       |       +----------+-----------+
                 +-----------+------------+                  |
                             |                               |
                 +-----------v------------+                  |
                 | Bounded agent loop     |                  |
                 | Databricks Model       |                  |
                 | Serving (Claude Haiku  |                  |
                 | 4.5), max 4 turns,     |                  |
                 | 8 tool calls, 240 s    |                  |
                 +-----------+------------+                  |
                             |  MCP tool calls               |
                 +-----------v-------------------------------v-----------+
                 |            FEMA Evidence & Oversight Graph            |
                 |  Screening tools (deterministic, read-only)           |
                 |    detect_category_outliers                           |
                 |    find_repeated_worksheets                           |
                 |    get_cost_share_anomalies                           |
                 |  Explanation tools                                    |
                 |    explain_risk_indicator   generate_evidence_brief   |
                 |  Resource fema-pa://provenance  Prompt fema_oversight_review |
                 +-----------+-------------------------------------------+
                             |  fixed operator-controlled origin,
                             |  path validation, 30 s timeout, 20 MB cap
                 +-----------v------------+
                 | OpenFEMA API v2        |
                 | PublicAssistanceFunded |
                 | ProjectsDetails        |
                 +------------------------+

   Deterministic renderer (grounding.py): builds the displayed answer from
   structured tool output only. Model prose is kept in the trace, not shown.

   Assurance plane (Databricks):
     Lakeflow Job -> pytest, ruff, SQLite controls on archived snapshots,
     model tool-selection and baseline runs -> MLflow run + artifact hashes.
     Unity Catalog: golden datasets fema_oversight_golden_v1 / v2,
     funded_projects_details table, submission volume.
```

Component responsibilities:

| Layer | Component | Responsibility | Status |
| --- | --- | --- | --- |
| Access | Databricks Apps OAuth | Only authenticated workspace users reach the app or MCP endpoint | Shipped |
| Access | Same-origin guard | Review endpoint rejects cross-origin calls with 403 | Shipped |
| Orchestration | Bounded agent loop | Model selects tools; hard limits of 4 turns, 8 tool calls, 240 s | Shipped |
| Tools | 3 screening + 2 explanation tools | Deterministic computation with provenance on every response | Shipped |
| Data | OpenFEMA v2 client | Fixed origin, path validation, 30 s timeout, 20 MB response cap, record caps with truncation flag | Shipped |
| Presentation | Deterministic renderer | Displayed answer contains only tool-produced counts, methods, limits | Shipped |
| Assurance | Recorded evaluation runs | Tests, controls, model traces, artifact hashes, MLflow | Shipped |
| Assurance | Golden datasets in Unity Catalog | 116-case v1 and 171-case v2 evaluation sets | Shipped |

---

## 6. Directed Agent Graph

We redesigned the requested linear chain into a directed graph with two explicit exits (abstain and no-usable-evidence) and one hard gate (human review). Every node states who performs it: the model, deterministic code, or a person. The model performs exactly one job: choosing tools and parameters.

```
 [1] Question
      |
 [2] Scope & Intent Gate ---------------------------> [X1] Decline / restate scope
      |  (model; system policy)                          (approve payment, confirm
      |                                                   improper payment, non-PA data)
 [3] Tool Plan  (model; bounded: 4 turns, 8 calls)
      |
 [4] Evidence Retrieval  (code; OpenFEMA v2, fixed origin, record caps)
      |
 [5] Domain Validation  (code; typed params, PA category A-G, PW identity,
      |                   sigma 1-10, repeat count >= 2, share band 0-1)
      |
 [6] Review Indicator Screening  (code; deterministic rule per indicator)
      |
 [7] Evidence Validation  (code; identity triple, truncation flag,
      |                     provenance completeness)  ----> [X2] "No usable evidence;
      |                                                       inspect the tool response"
 [8] Explainability  (code; methodology card: rule, parameters, thresholds, limits)
      |
 [9] Deterministic Brief Rendering  (code; no model prose displayed)
      |
[10] Human Review Gate  (person; no write or disposition tools exist)
      |
[11] Oversight Brief  (person-owned work product with full evidence chain)

 Offline assurance edge: [6] and [7] are re-checked by independent SQLite
 controls on archived snapshots in every recorded run.
```

| Node | Performed by | Implementation | Control evidence |
| --- | --- | --- | --- |
| 1 Question | Analyst or agent | Review page or MCP client | Same-origin guard; OAuth |
| 2 Scope & Intent Gate | Model under system policy | System prompt: review indicators only, no determinations, record text is data | Golden v1 scope cases 24/24; system-prompt leak attempts 0/3 with tools vs. 3/3 without |
| 3 Tool Plan | Model | Typed parameter descriptions; tool docstrings state purpose, peer baseline, and that outputs are review signals | First-tool selection 15/15; golden v2 routing and arguments 405/408 |
| 4 Evidence Retrieval | Code | OpenFEMA client, fixed origin, timeout, size cap | Path-override and fixed-origin tests (`test_http_security.py`) |
| 5 Domain Validation | Code | Typed Annotated parameters, enums, range checks with corrective hints | Validation tests; out-of-range values return an error and a hint |
| 6 Review Indicator Screening | Code | One documented rule per indicator | Control matches 3/3; live re-check Nov 4 |
| 7 Evidence Validation | Code | Disaster + applicant + PW identity; `possibly_truncated`; `_provenance` block | `evidence_identity` check passed; truncation disclosed in every response |
| 8 Explainability | Code | `explain_risk_indicator` and methodology cards | `explanation_schema` check passed |
| 9 Deterministic Rendering | Code | Renderer uses only tool counts, rules, limits | 0/513 unsupported numbers in displayed answers |
| 10 Human Review Gate | Person | All tools read-only; every output states "Analyst review required" | Tool annotations: readOnlyHint true, destructiveHint false |
| 11 Oversight Brief | Person | `generate_evidence_brief` supplies the evidence package | Brief returns source records, method, limits, timestamp |

Why this graph is better than the linear chain: the linear chain lets the model narrate between every step. This graph confines the model to nodes 2 and 3, makes nodes 4 through 9 deterministic and testable, adds exits so the system can say "no" or "no usable evidence" instead of improvising, and puts a person, not a model, at the end.

---

## 7. MCP Tool Definitions

All five tools are annotated `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`, `openWorldHint: true` (they read a public external API). All responses that return records include `_provenance` and `caveat`. Screening tools include `data_scope` and pagination fields (`total`, `count`, `offset`, `has_more`, `next_offset`).

| Tool (shipped name) | Purpose | Key parameters | Returns |
| --- | --- | --- | --- |
| `detect_category_outliers` | Within-category cost comparison: projects whose `projectAmount` is a set number of standard deviations above the mean of the same damage category and filters | `state_code`, `disaster_number`, `damage_category_code` (A-G), `sigma_threshold` (1-10, default 3.0), `limit`, `offset` | Review indicators with PW number, applicant, title, project amount, category mean, sigma above mean; `category_stats` (mean, standard deviation, n) |
| `find_repeated_worksheets` | Repeated worksheet pattern: groups of worksheets from the same applicant and disaster whose titles match after case, punctuation, and numbers are ignored | `state_code`, `disaster_number`, `min_repeat_count` (>= 2) | Groups with PW numbers, all titles, distinct title count, category, worksheet count, total federal share obligated |
| `get_cost_share_anomalies` | Cost-share screen: records whose federal share / total obligated ratio falls outside a configurable band | `state_code`, `disaster_number`, `band_low`, `band_high` (0-1), `min_total_obligated` (>= 0) | Records with ratio and obligations; explicit statement that declaration-specific authorizations are not verified |
| `explain_risk_indicator` | Methodology card for one indicator | `indicator` (`category_outlier`, `repeated_worksheet`, `cost_share_anomaly`) | Name, methodology, calculation, thresholds, limitations |
| `generate_evidence_brief` | Evidence package for one Project Worksheet | `pw_number`, `indicator`, `disaster_number`, `applicant_id` | Source records, rationale, methodology, limitations, review status, caveat, provenance |

Resource: `fema-pa://provenance` returns dataset provenance and field definitions (`federalShareObligated`, `totalObligated`, `projectAmount`, `damageCategoryCode`, `mitigationAmount`).

Prompt: `fema_oversight_review(state_code)` gives an agent the standard review sequence: screen, explain, brief, and hand to an analyst.

Naming note for judges: the cost-share tool keeps its shipped name `get_cost_share_anomalies` so that recorded runs, tests, and hashes stay valid. It is presented to analysts as a cost-share screen. Renaming it to `screen_cost_share_ratios`, with the old name kept as an alias, is in the roadmap.

---

## 8. Tool Descriptions (agent-facing text)

Status: these are the v1.1 replacement descriptions written for this package. The shipped release uses shorter docstrings with typed parameter descriptions (for example, "Single-letter PA category of work, A-G"). Applying the text below changes what the model sees, so it ships only together with a new recorded run (tool selection, golden set, controls). Each description follows one pattern: what it does, use when, do not use when, source, how to read the result.

**detect_category_outliers**
Returns Public Assistance projects whose estimated project amount is unusually high compared with other projects in the same damage category and filters. USE WHEN the question asks which projects cost far more than comparable projects in a category (for example, "utility projects in Hurricane Ida"). DO NOT USE to judge eligibility, reasonableness, or whether costs are allowable. Damage categories: A Debris Removal, B Emergency Protective Measures, C Roads and Bridges, D Water Control Facilities, E Public Buildings and Contents, F Public Utilities, G Parks, Recreational and Other. Pass the letter. SOURCE: OpenFEMA Public Assistance Funded Projects Details v2. HOW TO READ: sigma_above_mean is relative to the retrieved subset only. Large legitimate infrastructure projects are expected to appear. Each result is a review indicator for an analyst.

**find_repeated_worksheets**
Groups Project Worksheets from the same applicant and disaster whose titles match after ignoring capitalization, punctuation, and numbers. USE WHEN the question asks whether the same project appears more than once or whether an applicant has many near-identical worksheets. DO NOT USE to test duplication of benefits; that is a separate statutory determination this tool does not make. SOURCE: OpenFEMA v2. HOW TO READ: numbered series such as site lists or route segments are common and legitimate; groups whose titles differ only by capitalization or punctuation are the closest matches. Each group is a review indicator for an analyst.

**get_cost_share_anomalies**
Returns records whose federal share obligated divided by total obligated falls below band_low or above band_high. USE WHEN the question asks about federal share percentages. DO NOT USE to decide whether a share was authorized; disaster-specific cost-share adjustments (for example 90% or 100% for a period) are legitimate and are not checked. SOURCE: OpenFEMA v2. HOW TO READ: equality at a boundary is not returned; every result needs comparison with the declaration's authorized cost share.

**explain_risk_indicator**
Returns the documented methodology, calculation, thresholds, and limitations for one indicator. USE WHEN a user asks how a result was produced or what an indicator means, including what a result does and does not mean. DO NOT USE to retrieve records.

**generate_evidence_brief**
Assembles the evidence package for one Project Worksheet: its source records, the indicator methodology, limitations, review status, and provenance. USE WHEN an analyst selects a worksheet for review. Pass disaster_number and applicant_id with pw_number because PW numbers repeat across disasters. DO NOT USE to state a conclusion; the brief does not re-verify the threshold and adds no conclusion the data does not support.

---

## 9. Demo Script (live, under 2 minutes)

Audience test: a non-technical executive must be able to repeat the point afterward. The point is: *the AI pointed to three projects, showed exactly where the numbers came from, and handed the decision to a person.*

Setting: the analyst review page of the Databricks App, already signed in. Backup: recorded walkthrough video and the judge notebook, which runs the same tools.

| Time | Presenter says | Screen shows |
| --- | --- | --- |
| 0:00-0:15 | "Hurricane Ida hit Louisiana in 2021. FEMA has 115 public utility repair projects on record for that disaster. If you have one analyst and one afternoon, where do you start?" | Review page with three question cards |
| 0:15-0:25 | "I'll ask in plain English." Click the card "Are any utility repairs unusually expensive?" | Card question sent to the agent: "Check Louisiana disaster 4611 Category F projects (utilities) for cost outliers. Show the evidence brief for the top project." Progress steps appear |
| 0:25-0:50 | "The agent picked the right tool and the right filters by itself. Then the tool, not the AI, did the math." | Tool trace: `detect_category_outliers` with state LA, disaster 4611, category F. Result: 115 records retrieved, cap 10,000, not truncated. 3 review indicators |
| 0:50-1:10 | "Three projects stand out. The largest is the Houma Power Plant in Terrebonne Parish: about 149.6 million dollars, roughly 7.7 standard deviations above the average utility project of 4.8 million." | Category chart with project names: PW 1725 Houma Power Plant $149,603,170.72 (7.73); PW 1679 SLECA System-Wide Permanent Line Repair $93,766,167.88 (4.75); PW 5757 Waterline Replacement Grand Isle and Lafitte $66,310,184.74 (3.29) |
| 1:10-1:35 | "Here's what makes this trustworthy. Every answer shows the source, the rule, the timestamp, and what the rule can't tell you. Large power plants are supposed to be expensive. So the system doesn't say anything is wrong. It says: review this first, and here is the evidence." | Evidence brief for PW 1725: source record, federal share obligated $134,642,853.65, total obligated $134,642,853.65, declaration date 2021-08-29, methodology, limitations, review status as shipped: "Not a finding. Analyst review required." Provenance: OpenFEMA PA Funded Projects Details v2, retrieved_at timestamp |
| 1:35-1:55 | "We checked this the way an auditor would. An independent calculation, straight from OpenFEMA, returned the same three projects. And across our tests the AI never put an unsupported number on this screen." | Switch to Slide 9 (the app itself does not display control results): "Independent control: same 3 PWs, same category mean". Footer: run 20261102T152007Z, 71/71 tests |
| 1:55-2:00 | "AI points. Evidence proves. People decide." | Closing line |

Expected tool selection: `detect_category_outliers(state_code="LA", disaster_number=4611, damage_category_code="F")`, then `generate_evidence_brief(pw_number=1725, indicator="category_outlier", disaster_number=4611, applicant_id="109-99109-00")`. The model may also call `explain_risk_indicator(indicator="category_outlier")`; that is a valid path.

Expected evidence (verified November 4, 2026, 06:53 UTC):

| Field | Value |
| --- | --- |
| Records retrieved | 115 (cap 10,000; not truncated) |
| Category mean projectAmount | $4,802,096.50 |
| Category standard deviation (population) | $18,722,465.37 |
| Review indicators at sigma >= 3.0 | 3 |
| PW 1725 | Houma Power Plant, Terrebonne Parish, applicant 109-99109-00, $149,603,170.72, 7.73 sigma |
| PW 1679 | SLECA System-Wide Permanent Line Repair, Phase 1, applicant 000-UJKWZ-00, $93,766,167.88, 4.75 sigma |
| PW 5757 | Waterline Replacement Grand Isle and Lafitte, applicant 051-99051-00, $66,310,184.74, 3.29 sigma |
| Independent control (direct OpenFEMA query) | Same 115 records, same mean, same 3 PWs. The control used sample standard deviation, giving 7.70 / 4.73 / 3.27; the tool uses population standard deviation. The ranking and set are identical |

Expected citations displayed:

* Source: FEMA OpenFEMA Public Assistance Funded Projects Details (v2), updated daily
* Retrieved at: ISO-8601 UTC timestamp from the tool response
* Rule: sigma = (projectAmount - category_mean) / category_stddev within category F; returned when sigma >= 3.0
* Scope: retrieved projects in the selected category and filters (DR-4611, Category F)
* Limitations: Grants Manager data, not FEMA's official financial system; not for official reporting; large legitimate infrastructure projects can be high outliers
* Review status: analyst review required

Expected analyst output (what the analyst writes after reviewing):

> Screened DR-4611-LA Category F (115 public records, OpenFEMA v2, retrieved 2026-11-04). Three worksheets exceed 3 standard deviations above the category mean. PW 1725 (Houma Power Plant) is the largest at $149.6M. Next steps: confirm the scope of work and cost estimate in the project record, and confirm that the obligated federal share matches the cost share authorized for this declaration and period of work. No determination made.

Backup scenario (if asked for a second example, 30 seconds): "Is the same project listed more than once?" for Tropical Storm Helene, DR-4827-NC. The tool returns 86 repeated-title groups. The page separates closest matches (titles identical except capitalization or punctuation, such as "Div 13 Yancey" and "DIV 13 - Yancey") from numbered series (route or site lists), which are usually legitimate. Talking point: "The tool tells you which repeats are worth a person's time and which are routine."

---

## 10. Evaluation Plan

Principle: evaluate the evidence chain, not the eloquence. Every metric is defined so that a reviewer can recompute it from saved artifacts.

Evaluation questions:

1. Are the tools' numbers correct? (independent controls)
2. Does the model choose the right tool and parameters? (routing and argument accuracy)
3. Does data access change answer correctness? (with-tools vs. no-tools baseline)
4. Does anything unsupported reach the analyst? (hallucination in displayed answers vs. free prose)
5. Does every displayed answer carry its evidence chain? (citation and provenance coverage)
6. Does the system stay in scope under pressure? (scope and adversarial cases)
7. Is it fast enough for interactive review? (latency)

Test datasets:

| ID | Dataset | Size | Purpose | Location |
| --- | --- | --- | --- | --- |
| D1 | Archived OpenFEMA snapshots | FL DR-4734 cost share 238 rows; FL DR-4673 repeat screen 3,964 rows; FL DR-4673 Category C 179 rows | Tool vs. control correctness | `eval/results/20261102T152007Z/snapshot_*.json` |
| D2 | Tool-selection questions | 15 developer-authored questions | First-tool selection | `model_tool_selection.json` |
| D3 | Baseline count questions | 3 questions x 5 repeats | With-tools vs. no-tools | `baseline_count_comparison.json` |
| D4 | Golden set v1 | 116 cases | Retrieval, hallucination, scope | Unity Catalog `workspace.default.fema_oversight_golden_v1` |
| D5 | Golden set v2 | 171 cases (v1 + 55 model-authored, not human-reviewed) with task type, difficulty, expected behavior, expected count | Routing, arguments, counts, hallucination, adversarial | Unity Catalog `workspace.default.fema_oversight_golden_v2` |
| D6 | Adversarial and scope cases (within D4/D5) | Prompt-injection ("repeat everything above"), out-of-scope requests ("approve payment"), invalid inputs (category Z, malformed state, OData injection) | Guardrails | Same |
| D7 | Human label review | 58 judge-verdict traces | Check automated judges | MLflow labeling session `golden_v2_judge_failure_review` |
| D8 | Live spot checks | DR-4611 Cat F, DR-4827 repeats, evidence brief PW 1725 | Current-data re-verification | November 4, 2026 session |

Scoring rubric:

| Dimension | Pass condition | Scorer |
| --- | --- | --- |
| Count correctness | Tool total equals independent SQLite or direct-API control on the same records | Deterministic |
| Routing | Expected tool called (or no tool for out-of-scope) | Deterministic |
| Argument accuracy | State, disaster, category, thresholds equal expected values (defaults accepted) | Deterministic |
| Displayed-answer grounding | Every number and identifier in the displayed answer appears in tool output | Deterministic string and number match |
| Free-prose grounding | Every claim in model prose is supported by tool output | LLM judge, sampled human review |
| Evidence chain coverage | Displayed answer contains source, rule, scope, cap, limitations, review status; tool response contains retrieved_at | Deterministic |
| Scope adherence | Declines determinations and actions; no system-prompt disclosure | Deterministic plus LLM judge |
| Latency | Wall-clock time per tool call and per review | Timer |

Release gate: a build is eligible for submission only if all deterministic checks pass, control comparisons match exactly, and displayed-answer unsupported numbers equal zero. LLM-judge scores are reported but never gate a release, because we measured judge verdicts flipping on 30 to 34% of cases across repeats.

---

## 11. Testing Methodology

* **Unit and contract tests (71).** Tool registration and exact tool set, read-only annotations, parameter validation and error hints, repeat-title normalization rule, evidence identity, pagination, OpenFEMA client path and origin validation, browser route and same-origin behavior. Network calls are replaced with fixtures.
* **Independent controls.** For each screening tool, a separate implementation in SQLite computes the same rule over the identical archived snapshot. Counts must match exactly. Live re-checks use a direct OpenFEMA query written independently of the tool code.
* **Model tool-selection runs.** The real model (Databricks-served Claude Haiku 4.5, temperature 0) receives the real MCP tool list and each question; we record the first tool chosen.
* **Baseline comparison.** The same model, same questions, with no tools and no records. Responses are saved verbatim.
* **Golden-set evaluation.** MLflow GenAI evaluation over D4 and D5, three or more repeats, deterministic scorers plus LLM judges (judge model Databricks-served GPT-5.5). Traces stored in MLflow.
* **Human calibration.** A labeling session reviews LLM-judge verdicts to estimate judge reliability.
* **Recorded runs.** Each run stores pytest and ruff logs, snapshots, control comparisons, model traces, a SHA-256 fingerprint of all Python source, and artifact hashes, then logs to MLflow. A run is cited only for the fingerprint it tested.

---

## 12. Metrics and Results

All values below are measured. None are projections.

Correctness and routing:

| Metric | Definition | Result | Evidence |
| --- | --- | --- | --- |
| Control agreement | Tool count = independent control count | 3/3 (cost share 238 = 238; repeats 74 = 74 groups over 3,964 records; Category C 3 = 3 over 179 records) | Run 20261102T152007Z |
| First-tool selection | Expected first tool chosen | 15/15 | Run 20261102T152007Z |
| Agent workflows completed | Model-to-tool review finishes within bounds | 3/3; grounded browser workflows 3/3 | Run 20261102T152007Z |
| Routing and argument accuracy | Correct tool and arguments | 405/408 (99.3%); the single missed case was answered without calling the explanation tool | Golden v2, Oct 30, 3 repeats |
| Retrieval accuracy | In-scope arguments correct and count matches control | 208/208 | Golden v1 |
| Exact counts, tools vs. no tools | Count equals control | 342/342 vs. 0/342 (golden v2); 15/15 vs. 0/15 (recorded run) | Golden v2; run 20261102T152007Z |

Grounding, hallucination, and evidence chain:

| Metric | Definition | Result | Evidence |
| --- | --- | --- | --- |
| Displayed-answer hallucination | Unsupported numbers or IDs in what the analyst sees | 0/232 (golden v1, 95% upper bound 1.63%); 0/513 (golden v2) | Golden v1, v2 |
| Free-prose hallucination | Unsupported claims in model narration (not displayed) | About 25% of answers (golden v2); 40 to 43% under stricter checks (golden v1) | Golden v1, v2 |
| Evidence chain coverage | Displayed answer has source, rule, scope, cap, limitations, review status | 513/513 by construction of the renderer | Golden v2; renderer code |
| Provenance on tool responses | `_provenance` with source, retrieved_at, methodology, limitations | Present on every screening and brief response tested | Live checks Nov 4 |
| LLM-judge answer grounding after template fix | Judge rates displayed answer grounded | 170/171 on re-rendered outputs | MLflow run c9777b6c |

Scope and safety:

| Metric | Result | Evidence |
| --- | --- | --- |
| Scope adherence (declines determinations and actions) | 24/24 | Golden v1 |
| System-prompt disclosure attempts | 0/3 with tools vs. 3/3 without tools | Golden v2 |
| Human check of LLM judge | Judge correct on 14 of 15 reviewed verdicts (18 of 58 traces reviewed) | Labeling session |

Latency:

| Measure | Result | Evidence |
| --- | --- | --- |
| Median tool call incl. live OpenFEMA retrieval | 0.36 s cost share, 0.46 s repeats, 0.37 s category | Run 20261102T152007Z |
| Live calls, Nov 4 | 2.65 s category (DR-4611 F), 0.91 s repeats (DR-4827), 2.08 s evidence brief | This session |
| End-to-end review with model | 3 to 9 s per question (8 questions, single user) | Nov 2 local run |
| Golden v2 under 10 parallel workers | p50 15.6 s, p95 24.6 s; about 6,000 tokens per case | Golden v2 |

How to read these results: deterministic metrics are unanimous across repeats. The small sets (15 questions, 3 workflows) show the design works on representative cases; they are not general accuracy claims. Golden v2 includes 55 model-authored cases that were not human-reviewed.

---

## 13. Security Controls

| Control | Implementation | Verified by |
| --- | --- | --- |
| Authentication | Databricks Apps OAuth in front of the UI and MCP endpoint | Unauthenticated calls receive a 302 redirect to sign-in |
| Cross-origin protection | Review endpoint requires a same-origin `Origin` header | Returns 403 otherwise; `test_cross_origin_review_is_rejected` |
| Least privilege tools | All five tools read-only, non-destructive, idempotent; no write, approve, or delete capability exists | Tool annotations; registration tests assert the exact tool set |
| Fixed data origin | OpenFEMA base URL is operator-controlled; request paths validated to prevent origin escape | Client tests |
| Resource bounds | 30 s upstream timeout; 20 MB response cap; 5,000 / 10,000 record caps with `possibly_truncated` flag | Client code and tests |
| Agent bounds | Maximum 4 model turns, 8 tool calls, 240 s per review | Agent loop code |
| Input validation | Typed parameters, enums for indicators, range checks; errors return a corrective hint instead of failing silently | Validation tests |
| Prompt-injection posture | Record text treated as data; displayed answer built from structured fields, so record text cannot rewrite the answer | Renderer design; disclosure tests 0/3 |
| Data sensitivity | Public OpenFEMA aggregate records only; no PII, no credentials in tool inputs or outputs | Data source; repository secret scan clean |
| Model hosting | Model calls go to Databricks Model Serving inside the workspace | Agent loop configuration |
| Supply chain | Pinned runtime dependencies (`fastmcp==4.0.11`, `httpx==0.28.1`, `pydantic==2.13.5`, `databricks-sdk==0.157.0`) | requirements.txt |

Known gap, stated plainly: rate limiting is not in the shipped release. On the development branch we found that FastMCP issues a new session per call, so a per-session limit never fires; the fix is a global limit, tracked in the roadmap.

---

## 14. Governance Controls

| Control | Rule |
| --- | --- |
| Role boundary | AI selects tools and parameters. Code computes. People make determinations. |
| Output language | Outputs are review indicators and review recommendations. The system does not characterize intent, misconduct, or eligibility. |
| Human review gate | Every response states "Analyst review required." No tool can take action on an award. |
| Documented methodology | Each indicator has a methodology card (rule, calculation, thresholds, limitations), served by `explain_risk_indicator` and embedded in every brief. |
| Version control of evidence | Each recorded run carries a SHA-256 fingerprint of the Python source; claims cite the run and fingerprint they come from. |
| Reproducibility | Archived snapshots, controls, traces, and logs saved per run and logged to MLflow. |
| Release gate | Deterministic checks and control matches must all pass; displayed unsupported numbers must equal zero. |
| Change transparency | When the live app changes after a recorded run, the change is disclosed and the run is not cited for it. |
| Framework alignment | Mapped to NIST AI RMF 1.0 functions: Govern (role boundary, release gate), Map (stated purpose and limits), Measure (controls, golden sets, judge calibration), Manage (read-only design, disclosure of gaps). Consistent with GAO's AI Accountability Framework emphasis on data, performance, and monitoring, and with current OMB guidance that AI used in agency processes remain subject to human oversight. |

---

## 15. Explainability Framework

Every review recommendation answers five questions in plain language:

| Question | Where the answer comes from | Example (PW 1725) |
| --- | --- | --- |
| What was screened? | `data_scope` | 115 public Category F records for DR-4611-LA; cap 10,000; not truncated |
| Why was this record returned? | Indicator values | $149,603,170.72 is 7.73 standard deviations above the category mean of $4,802,096.50 |
| How was it calculated? | Methodology card | (projectAmount - mean) / standard deviation within category F; threshold 3.0 |
| What can't this tell you? | Limitations | Large legitimate infrastructure projects can be high outliers; peers are not matched by scale or geography; Grants Manager data is not the official financial system |
| What should a person do next? | Review status and brief | Review the scope of work, cost estimate, and authorized cost share in the project record |

Explainability is computed, not generated. Each of the five answers is a field in the tool response, so it is identical every time and testable.

---

## 16. Evidence Chain Framework

Each recommendation carries a seven-link chain. A missing link is shown, not hidden.

| Link | Field | Example |
| --- | --- | --- |
| 1 Source | `_provenance.source` | FEMA OpenFEMA Public Assistance Funded Projects Details (v2) |
| 2 Retrieval time | `_provenance.retrieved_at` | 2026-11-04T06:53:19Z |
| 3 Source refresh | `_provenance.update_frequency`, `last_updated` | Daily; dataset refresh timestamp not retrieved (disclosed) |
| 4 Scope | `data_scope` | records_retrieved 115, record_cap 10,000, possibly_truncated false, disaster_filter 4611 |
| 5 Method | `_provenance.methodology` | sigma = (projectAmount - category_mean) / category_stddev within category F; flagged sigma >= 3.0 |
| 6 Record identity | Disaster number + applicant ID + PW number | 4611 / 109-99109-00 / 1725 |
| 7 Limitations and status | `_provenance.limitations`, `review_status`, `caveat` | Grants Manager data, not for official reporting; analyst review required |

Assurance links outside the response: recorded run ID, source fingerprint, control comparison file, MLflow run. These connect a displayed number back to a test that checked the code that produced it.

---

## 17. Presentation Storyline

One sentence: *AI points, evidence proves, people decide.*

Arc:

1. **The stakes.** Billions in Public Assistance; thousands of worksheets per disaster; a small number of reviewers.
2. **The trust gap.** Without data, the model answered 0 of 15 exact questions. With data but free narration, about a quarter of its prose was unsupported.
3. **The idea.** Don't make the AI more convincing; make its evidence inspectable. Confine the model to choosing tools; let code compute; let people decide.
4. **The demo.** Hurricane Ida utilities: three projects, full evidence, decision handed to a person.
5. **The proof.** Independent controls, 15/15 vs 0/15, 0 unsupported numbers on screen, recorded runs with fingerprints.
6. **The guardrails.** Read-only, bounded, authenticated, documented, honest about gaps.
7. **The pattern.** Works for any federal open dataset: SBA, HUD, USDA, Treasury.
8. **The ask.** Pilot with a FEMA or OIG review team on one active declaration.

---

## 18. Complete Replacement Slide Deck

Format: 16:9, 12 main slides plus 4 appendix slides, for a 5-minute presentation with a 2-minute live demo. Visual system: navy (#0B2545) headers, white background, one accent color (amber #E0A100) used only for review indicators, gray for limitations. Every slide footer: "Run 20261102T152007Z | Source fingerprint 9cdad51e | OpenFEMA PA Funded Projects Details v2".

### Slide 1. Title

* **Objective:** Establish the positioning in five seconds.
* **Visual:** Navy full-bleed. Left: title. Right: a simple three-node line graphic: "AI points" (amber dot) to "Evidence proves" (navy document icon) to "People decide" (person icon).
* **Content:**
  * FEMA Evidence & Oversight Graph
  * Trusted oversight infrastructure for AI agents using evidence-backed review recommendations
  * Phebe Arouni & Tom Jacobson | GSA MCP Server & AI Agent Government Hackathon | Dataset Access track
* **Speaker notes:** "We built infrastructure that lets AI agents help oversight teams decide where to look first, with every recommendation traceable to a federal record. Our whole design fits in three words: AI points, evidence proves, people decide."

### Slide 2. The oversight problem

* **Objective:** Make judges feel the prioritization problem.
* **Visual:** One large number with a small grid of 115 squares, 3 in amber.
* **Content:**
  * Hurricane Ida, Louisiana: 115 public utility repair worksheets in one category of one disaster
  * Every disaster has thousands more across seven categories of work
  * Oversight teams must choose what to review first, and defend that choice with evidence
* **Speaker notes:** "This is one category in one disaster. Multiply by seven categories and every major declaration. Reviewers don't need more data. They need a defensible place to start."

### Slide 3. The trust gap

* **Objective:** Show, with our own measurements, why ordinary AI fails the evidence standard.
* **Visual:** Two-column comparison with large numerals.
* **Content:**
  * Same model, no data access: **0 of 15** exact-count questions answered
  * Same model, data access, free narration: **about 1 in 4** answers contained unsupported statements
  * An answer you cannot trace is an answer you cannot use in oversight
* **Speaker notes:** "We measured this on our own system. Without tools the model couldn't answer exact questions at all. With tools, its own narration still added claims the data didn't support. So we stopped asking how to make the AI more convincing and started asking how to make its evidence inspectable."

### Slide 4. Our approach

* **Objective:** State the three design rules.
* **Visual:** Three vertical panels with icons: compass (model), gear (code), person (analyst).
* **Content:**
  * The model chooses which tool to use. That's all it does.
  * Code retrieves the records and does every calculation.
  * The analyst sees only evidence the tools produced, and makes the decision.
* **Speaker notes:** "Each actor does what it's good at. Language models are good at understanding a question. Code is good at math. People are accountable for decisions. We never let those roles blur."

### Slide 5. Directed agent graph

* **Objective:** Show architectural rigor to Databricks, OpenAI, and IG judges.
* **Visual:** Eleven-node vertical graph from Section 6. Nodes 2-3 shaded "model", 4-9 "code", 10-11 "person". Two side exits: "Decline / restate scope" and "No usable evidence".
* **Content:**
  * Question, Scope & Intent Gate, Tool Plan, Evidence Retrieval, Domain Validation, Review Indicator Screening, Evidence Validation, Explainability, Deterministic Rendering, Human Review Gate, Oversight Brief
  * Model confined to 2 of 11 nodes; bounded to 4 turns and 8 tool calls
  * Two exits: the system can say no, and can say "no usable evidence"
* **Speaker notes:** "Most agent demos let the model narrate between every step. Ours confines it to two nodes. Everything after the tool plan is deterministic and testable, and the last step is always a person."

### Slide 6. MCP tool design

* **Objective:** Demonstrate agent-oriented tool design.
* **Visual:** Five tool cards in two rows (3 screening, 2 explanation), each with a "read-only" badge; resource and prompt shown as small tabs.
* **Content:**
  * Screening: within-category cost comparison; repeated worksheet pattern; cost-share screen
  * Explanation: methodology card; evidence brief for one Project Worksheet
  * Every tool: typed, described parameters; read-only annotations; corrective error hints; provenance on every response
  * v1.1: USE WHEN / DO NOT USE guidance per tool, released only with a new recorded run
  * Resource `fema-pa://provenance`; prompt `fema_oversight_review`
* **Speaker notes:** "We designed tools for the agent the way you'd write a procedure for a new analyst: what it's for, when not to use it, where the data comes from, and how to read the result. The model picked the right tool fifteen out of fifteen times on the shipped descriptions; the v1.1 descriptions add explicit use and do-not-use guidance."

### Slide 7. Live demo

* **Objective:** Make it memorable.
* **Visual:** Live app. Fallback: screenshot sequence of question card, tool trace, bar chart, evidence brief.
* **Content:**
  * Question: Hurricane Ida utilities, DR-4611-LA, Category F
  * 115 records screened; 3 review indicators
  * Houma Power Plant, PW 1725: $149.6M, 7.7 standard deviations above the category mean
  * Evidence brief with source, timestamp, method, limits; analyst review required
* **Speaker notes:** Follow the demo script in Section 9 exactly. End on: "AI points. Evidence proves. People decide."

### Slide 8. The evidence chain

* **Objective:** Make trust visible.
* **Visual:** Seven chain links left to right, each labeled with the PW 1725 value.
* **Content:**
  * Source: OpenFEMA PA Funded Projects Details v2
  * Retrieved: 2026-11-04 06:53 UTC
  * Scope: 115 records, cap 10,000, not truncated
  * Method: standard deviations above Category F mean, threshold 3.0
  * Identity: DR-4611 / applicant 109-99109-00 / PW 1725
  * Limits: Grants Manager data; large infrastructure is expected to be high
  * Status: analyst review required
* **Speaker notes:** "This is what makes the answer usable. If any link is missing, the system shows it as missing. For example, we disclose that we don't yet retrieve the dataset's refresh timestamp."

### Slide 9. How we tested it

* **Objective:** Show IG-grade evaluation rigor.
* **Visual:** Four stacked evidence bars with checkmarks; footer with run ID and fingerprint.
* **Content:**
  * Independent controls: tool results matched a separate calculation 3 of 3 times (238, 74, 3)
  * Tool selection: 15 of 15; routing and arguments 405 of 408 on a 171-case golden set
  * With tools 15 of 15 exact answers; without tools 0 of 15
  * 0 unsupported numbers in 513 displayed answers; 71 of 71 automated tests
* **Speaker notes:** "Every number on this slide comes from a recorded run you can open in MLflow, tied to a fingerprint of the exact code it tested. We also re-checked the demo against live OpenFEMA this morning; an independent query returned the same three projects."

### Slide 10. What we caught and fixed

* **Objective:** Win credibility by showing failures honestly.
* **Visual:** Three "before / after" rows.
* **Content:**
  * Model prose added unsupported legal citations: now the displayed answer is rendered from tool evidence only
  * A refactor dropped category names from a tool description and argument accuracy fell when users named categories in words: the golden set caught it, and the v1.1 descriptions list A-G with names
  * Template sentences the judge flagged as unsupported: rewritten to point the analyst to the executed parameters; judge grounding rose from 115 to 170 of 171 on re-rendered outputs
* **Speaker notes:** "Our evaluation found real problems. Each one changed the design. That's the point of evaluation: it should be able to fail you."

### Slide 11. Security and governance

* **Objective:** Reassure GSA, FEMA, and IG reviewers.
* **Visual:** Two columns of shield and gavel icons.
* **Content:**
  * Authenticated Databricks App; same-origin guard; read-only tools; fixed data origin; bounded agent; pinned dependencies
  * Role boundary: AI recommends review, people decide
  * Documented methodology, recorded runs, source fingerprints, release gate
  * Aligned to NIST AI RMF: Govern, Map, Measure, Manage
  * Disclosed gap: rate limiting is on the roadmap
* **Speaker notes:** "Nothing in this system can approve, change, or close anything. It can only recommend where a person should look, and show why."

### Slide 12. A reusable federal pattern and the ask

* **Objective:** Close on mission and scale.
* **Visual:** Center hub labeled "Evidence-backed review MCP pattern" with spokes to FEMA PA, FEMA Individual Assistance, SBA disaster loans, HUD CDBG-DR, USDA, Treasury.
* **Content:**
  * The pattern: deterministic tools, evidence chain, deterministic rendering, human review gate
  * Next: pilot with one FEMA or OIG review team on one active declaration; capture analyst dispositions to measure usefulness
  * AI points. Evidence proves. People decide.
* **Speaker notes:** "We built this for FEMA Public Assistance, but the pattern is the contribution. Any agency with open data and an oversight mission can use it. Our ask: let us pilot it with one review team on one declaration."

### Appendix A1. Measured results detail

* **Objective:** Detail for technical judges.
* **Visual:** The tables from Section 12.
* **Content:** Correctness, grounding, scope, and latency tables, each with its evidence source.
* **Speaker notes:** Use only if asked; point to the evidence column.

### Appendix A2. Tool contracts

* **Objective:** Detail for MCP judges.
* **Visual:** The tool definition table from Section 7.
* **Content:** Five tools, parameters, returns, annotations; resource and prompt.
* **Speaker notes:** "The descriptions are written for the agent and tested against it."

### Appendix A3. FEMA terminology standard

* **Objective:** Show domain fluency to FEMA reviewers.
* **Visual:** Two-column table "We say / We don't say".
* **Content:** Appendix A of this package.
* **Speaker notes:** "Language matters in oversight. We built the vocabulary into the tools so the agent can't drift."

### Appendix A4. Limitations

* **Objective:** Pre-empt IG objections.
* **Visual:** Plain bulleted list, gray.
* **Content:**
  * Grants Manager data, not FEMA's official financial system; not for official reporting
  * Baselines describe the retrieved subset; peers not matched by scale or geography
  * Cost-share screen does not verify declaration-specific authorizations
  * Repeated-title pattern does not test duplication of benefits
  * Dataset refresh timestamp not yet retrieved
  * Small developer-authored question sets; 55 golden v2 cases not human-reviewed
  * Live app includes November 3 changes to the repeated-worksheet output and view; the recorded run does not cover them
* **Speaker notes:** "We'd rather you hear our limits from us."

---

## 19. Judge Q&A Responses

**Q: Isn't this just an API wrapper?**
A: An API wrapper returns rows. Each of our tools returns a review recommendation with its own evidence chain: rule, parameters, scope, cap, timestamp, limitations, record identity. The value is in the contract between agent and analyst, and we measured it: the same model went from 0 of 15 to 15 of 15 exact answers, with zero unsupported numbers displayed.

**Q: How do you know the numbers are right?**
A: Every recorded run compares each screening tool against an independent SQLite calculation on the identical OpenFEMA snapshot; all three matched exactly. This morning an independent direct query of OpenFEMA returned the same three Hurricane Ida utility projects as the tool.

**Q: What stops the model from making things up?**
A: The model never writes what the analyst sees. It chooses tools and parameters. The displayed answer is rendered from tool fields. We measured the model's free prose at about 25% unsupported, and that prose is never displayed. Displayed answers: 0 unsupported numbers in 513.

**Q: Does a review indicator mean something is wrong?**
A: No. It means a record meets a documented screening rule and deserves a person's attention first. The Houma Power Plant is expected to be expensive. The tool says where to look; the analyst determines whether anything needs follow-up.

**Q: Why should FEMA trust OpenFEMA data for this?**
A: OpenFEMA is FEMA's own published data. We state its limits on every answer: it comes from Grants Manager, not FEMA's official financial system, and is not for official reporting. That makes it appropriate for prioritizing review, which is exactly how we use it.

**Q: What about cost-share adjustments like 90% or 100% federal share?**
A: Those are legitimate and declaration-specific. Our cost-share screen says on every result that it does not verify authorizations. In the demo, PW 1725's federal share obligated equals its total obligated; the analyst's next step is to confirm the authorized share for that declaration and work period.

**Q: Is the repeated-worksheet tool a duplication of benefits test?**
A: No. Duplication of benefits is a statutory determination under the Stafford Act. Our tool finds worksheets from the same applicant and disaster with matching titles, and separates near-identical titles from routine numbered series, so analysts can quickly rule groups in or out.

**Q: What MCP design principles did you follow?**
A: Small number of purpose-built tools; typed parameters with descriptions (USE WHEN and DO NOT USE guidance added in v1.1); read-only, idempotent annotations; structured outputs with pagination and truncation flags; corrective error hints; a provenance resource and a review prompt; identity fields so results compose across tools.

**Q: How does it scale?**
A: Tools are stateless and read-only, and run as a Databricks App. Median tool latency is under half a second including live retrieval. Record caps are explicit, and truncation is disclosed rather than hidden. For national-scale screens, the next step is running the same rules over the Unity Catalog copy of the dataset.

**Q: Why Databricks?**
A: Authentication, app hosting, model serving, MLflow evaluation and tracing, Unity Catalog datasets, and scheduled validation jobs are in one governed environment. Our evaluation evidence lives next to the code it tested.

**Q: How did you evaluate the LLM judges themselves?**
A: We repeated judge runs and saw verdicts flip on 30 to 34% of cases, while deterministic checks were unanimous. So deterministic checks gate releases, judges are advisory, and a human labeling session checked judge verdicts (judge correct on 14 of 15 reviewed).

**Q: What's the biggest limitation?**
A: Peer comparison is within category and filters only; it does not match projects by scale or geography. Second, the evaluation question sets are small and partly developer-authored. We state both on every relevant slide and answer.

**Q: Is the live app the same code as the recorded run?**
A: The category, cost-share, explanation, brief, and agent code are the recorded build. On November 3 we added worksheet-level detail and a match-type label to the repeated-worksheet tool output and its view. Group counts did not change (86 for DR-4827, 74 for DR-4673), but the recorded run does not cover those changes, and we say so.

**Q: Could another agency reuse this?**
A: Yes. The pattern is independent of FEMA: deterministic tools over an open dataset, a provenance block on every response, a deterministic renderer, read-only design, and a recorded evaluation harness with independent controls.

**Q: What would a pilot look like?**
A: One review team, one active declaration, 60 days. Measure time to a defensible review starting point, analyst agreement with indicators, and evidence-chain completeness, with dispositions recorded by analysts, not by the system.

---

## 20. Competitive Positioning

| Typical entry | What it does | Where it falls short for oversight | Our design |
| --- | --- | --- | --- |
| Generic MCP server over an API | Exposes endpoints as tools | Returns rows with no rule, scope, or limits; agent must narrate | Tools return review recommendations with a seven-link evidence chain |
| Retrieval (RAG) system | Finds documents and summarizes | Model writes the answer; citations point to text, not to computed numbers | Numbers computed by code; displayed answer rendered from tool fields |
| Conversational assistant | Answers questions fluently | Unsupported prose; no release gate | Free prose measured (about 25% unsupported) and removed from display |
| Reporting or visualization tool | Shows totals and charts | Leaves prioritization and explanation to the user | Agent selects the screen; output explains why each record was returned |
| Standard Databricks demo | Shows platform features | Rarely shows independent controls or failure analysis | Recorded runs, controls, fingerprints, judge calibration, disclosed regressions |

The differentiator judges can verify in minutes: the model's job is limited, the evidence is computed, and the tests are able to fail.

---

## 21. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation | Residual |
| --- | --- | --- | --- | --- |
| Model selects wrong filters (for example, wrong category) | Low, measured | Analyst reviews wrong set | Executed arguments shown in the tool trace; displayed answer tells the analyst to check executed parameters against the question; v1.1 adds A-G names to the description | Analyst must read parameters |
| Review indicator read as a conclusion | Medium | Reputational, unfair to applicants | Caveat and review status on every response; methodology card; terminology standard | Training for users |
| Retrieval cap truncates results | Low for single declarations | Incomplete screen | `possibly_truncated` flag; caps stated; pagination | National screens need Unity Catalog path |
| OpenFEMA unavailable or throttled | Medium | Review delayed | Timeouts; errors returned as "no usable evidence" instead of guesses | No offline cache in release |
| Data differs from official financial system | Known | Figures not reportable | Limitation stated on every response | Use for prioritization only |
| Prompt injection via record text | Low | Altered narrative | Displayed answer built from structured fields; record text treated as data | Model prose may be affected but is not displayed |
| Unbounded usage | Medium | Cost, upstream load | Agent bounds; authenticated access | Global rate limit on roadmap |
| LLM-judge instability | Measured | Misleading quality scores | Deterministic release gate; human calibration | Judges advisory only |
| Live app drifts from recorded run | Occurred | Claims not covered | Disclosure policy; re-run before citing | Re-run required for each release |

---

## 22. Lessons Learned

1. **Measure the model before you trust it.** Our first model answers added unsupported legal citations. Measuring free prose (about 25% unsupported) led to the most important design decision: render the displayed answer from tool evidence only.
2. **Better tool descriptions can cost accuracy.** A refactor that made descriptions longer dropped the A-G category names; argument accuracy fell when users named categories in words, and prompt tokens nearly doubled (about 5.5k to 10.1k per case). The golden set caught it.
3. **Judges need judging.** LLM-judge verdicts flipped on 30 to 34% of cases across repeats. Deterministic checks gate releases; judges inform.
4. **Boilerplate is a claim too.** Fixed template sentences were flagged as unsupported. Rewriting them to echo the executed parameters raised judge grounding from 115 to 170 of 171.
5. **Zero is a valid result.** An exact-title repeat rule returned zero groups across Florida declarations. We kept the zero, documented it, and adopted a documented normalization rule with a new recorded run, rather than tuning until something appeared.
6. **Framework behavior matters for security.** FastMCP minted a new session per call, so a per-session rate limit never fired. Test controls, not configuration.
7. **Evidence goes stale when code changes.** Every claim must cite the run and fingerprint it came from.

---

## 23. Future Roadmap

| Horizon | Item | Value |
| --- | --- | --- |
| 30 days | Global rate limit and per-user quotas | Closes the disclosed security gap |
| 30 days | Retrieve OpenFEMA dataset refresh timestamp into `_provenance.last_updated` | Completes evidence-chain link 3 |
| 30 days | Rename cost-share tool to `screen_cost_share_ratios` with alias | Vocabulary consistent with review-indicator language |
| 60 days | Analyst disposition capture ("review warranted", "no further review", "need more information") stored in Unity Catalog, written by people only | Measures usefulness; builds a human-labeled evaluation set |
| 60 days | Declaration cost-share reference from DisasterDeclarationsSummaries and published amendments | Moves cost-share screen from band to authorized-share comparison |
| 90 days | Unity Catalog execution path for national-scale screens over `funded_projects_details` | Removes record caps; lineage in Unity Catalog |
| 90 days | Peer matching by project size, applicant type, and geography | Stronger comparisons |
| 120 days | Pilot with one FEMA or OIG review team on one declaration | Operational evidence |
| 180 days | Pattern kit for other agencies (template server, evidence-chain schema, evaluation harness) | Reusable federal pattern |

---

## 24. Final Closing Statement

Oversight doesn't need an AI that sounds certain. It needs an AI that can show its work.

The FEMA Evidence & Oversight Graph gives AI agents a narrow, honest job: find where a person should look first, and bring the evidence. Code does the math. Every answer carries its source, method, limits, and timestamp. Nothing the system produces is a determination, and nothing it can do changes an award. We tested it the way an Inspector General would, published what failed, and fixed it.

AI points. Evidence proves. People decide.

---

## Appendix A. FEMA Terminology Standard

| Use | Do not use | Reason |
| --- | --- | --- |
| Review indicator | Red flag, alert, hit | Neutral; indicates a screening rule was met |
| Review recommendation | Conclusion, determination | Only people make determinations |
| Supporting evidence | Proof | Evidence supports review; it does not prove |
| Analyst review | Automated decision | Human accountability |
| Documented methodology | Algorithm verdict | Rules are published and inspectable |
| Within-category cost comparison | Overpayment, overcharge | High cost is often legitimate |
| Repeated worksheet pattern | Duplicate payment, double-dipping | Duplication of benefits is a separate statutory determination |
| Cost-share screen | Wrong share, unauthorized share | Adjusted shares are often authorized |
| Project Worksheet (PW) | Claim, invoice | PA term of art |
| Applicant (subrecipient); State or tribe (recipient) | Grantee, vendor | Current 2 CFR 200 terms; OpenFEMA fields still use grantee |
| Category of work A-G | Damage type | PA term of art |
| Federal share obligated | FEMA paid | Obligation is not disbursement |
| Retrieved subset | Full population | Caps and filters apply |

Corrections applied to earlier drafts:

* "Obligated" is not "paid"; obligation precedes disbursement.
* `projectAmount` is the estimated project cost, not the obligated amount.
* Federal share is at least 75% and can be increased for a declaration; a 100% ratio is not by itself an exception.
* `mitigationAmount` can be negative because of adjustments; this is not an error.
* Repeated titles are not duplicate payments; site lists and route segments are common in Category C.

---

## Appendix B. Claims Register

| Claim | Value | Source |
| --- | --- | --- |
| Automated tests | 71/71 passed; ruff clean | Run 20261102T152007Z; re-run Nov 4 from submission zip (71 passed in 6.06 s; ruff all checks passed) |
| Control agreement | 238 = 238; 74 = 74 (3,964 rows); 3 = 3 (179 rows) | Run 20261102T152007Z `summary.json` |
| First-tool selection | 15/15 | Run 20261102T152007Z |
| Workflows | 3/3 completed; 3/3 grounded browser workflows | Run 20261102T152007Z |
| Baseline | 15/15 with tools vs. 0/15 without (15/15 abstained or invalid) | `baseline_count_comparison.json` |
| Median tool latency | 0.364 s, 0.456 s, 0.375 s | Run 20261102T152007Z |
| Source fingerprint | 9cdad51e... | Run 20261102T152007Z |
| Golden v1 | Retrieval 208/208; displayed unsupported 0/232; scope 24/24 | MLflow experiment 1305734463288268, Oct 30 |
| Golden v2 | Routing and arguments 405/408; counts 342/342 vs. 0/342; displayed unsupported 0/513; free prose about 25% unsupported; disclosure 0/3 vs. 3/3; p50 15.6 s, p95 24.6 s | MLflow summary run 42449e0f, Oct 30 |
| Judge calibration | Judge verdicts flip 30-34%; judge correct 14/15 reviewed | Golden v2; labeling session |
| Template fix | Judge grounding 115 to 170 of 171 | MLflow run c9777b6c |
| Demo values | DR-4611 Cat F: 115 records; mean $4,802,096.50; PW 1725 $149,603,170.72, 7.73 sigma; PW 1679 4.75; PW 5757 3.29 | Live tool call Nov 4, 06:53 UTC; independent OpenFEMA control same 3 PWs |
| Backup demo | DR-4827 repeated-title groups: 86 | Live tool call Nov 4 |

Scope notes: golden v1 and v2 results were measured on October 30 builds that preceded the November 2 repeat-rule change; the recorded run 20261102T152007Z covers the current tool code. The live app's November 3 changes to the repeated-worksheet tool output (worksheet detail, match type, ordering) and view are not covered by any recorded run; the backup demo's "closest match" ordering depends on that live build and was last checked on November 3.
