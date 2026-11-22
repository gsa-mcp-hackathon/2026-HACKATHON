# FEMA Oversight MCP

FEMA Oversight MCP transforms public oversight data into traceable, evidence-backed review recommendations while keeping reviewers fully in control of every decision.

MCP Server and SI Agent Government Hackathon. Dataset Access Server track. Phebe Arouni and Tom Jacobson. Reconciled November 19, 2026.

Submitted server 1.1.0. Verified run 20261119T134625Z. Source fingerprint 6dee75f765962a954ca75ca7cb5884d5f198f48eac87d3408fa7cff78386dd98. The canonical implementation is the root src/fema_oversight directory.

[GitHub judge entry point](https://github.com/gsa-mcp-hackathon/2026-HACKATHON)

Read README.md first, then this package, docs/GSA_TEMPLATE_ALIGNMENT.md, docs/TOOLS.md and eval/README.md. The repository also contains the matching judges deck and full current evidence. The local MCP server is the submitted version. The older hosted Databricks analyst app is a separate v1.0 demonstration and is not required for judging v1.1.

Reproduce: uv sync --extra dev --frozen; uv run pytest -q; uv run python eval/run_evaluation.py. Offline checks use the included public-data fixture. Add --live for the four OpenFEMA checks. MCP arguments use a top-level params object, as shown in Section 7 and docs/TOOLS.md.

### Design principles

| Principle | What it means |
| --- | --- |
| Deterministic Evidence Generation | Code computes counts and statistics. Identical records and parameters reproduce the same calculations. Retrieval timestamps can change. |
| Complete Evidence Traceability | Data-bearing results carry provenance. Screens and queue add structured scope. Briefs add identity, method, re-check details and next steps. |
| Human Decision Authority | No tool can approve, change or close anything. The system recommends projects for review; reviewers make all decisions. |

The system recommends projects for review; reviewers make all decisions.

## 1. Executive Summary

FEMA Public Assistance reviewers must decide which funded projects warrant further review. In the November 19 live verification, Hurricane Ida in Louisiana (DR-4611) returned 3,648 funded-project records. The server helps reviewers prioritize this public evidence and reconstruct the rule behind each selection.

FEMA Oversight MCP gives an MCP-capable SI client six read-only actions over OpenFEMA. Code applies documented review rules and returns structured results. Data-bearing actions include provenance. Screens and queue report structured scope; the brief adds source records, a default-rule re-check and reviewer next steps. The client presents the evidence and the reviewer decides what follows.

Governance is built into the design. Every tool is read-only, and data comes from one fixed public source, OpenFEMA Public Assistance Funded Projects Details v2, reached through a fixed origin. Inputs are validated before tool logic runs. Outputs are review recommendations, never findings. The system recommends projects for review; reviewers make all decisions.

November 19 verification passed 37 of 37 MCP evaluation checks and, separately, 63 of 63 unit and contract tests. The 37 comprise controls (3), errors (19), contracts (5), stability (6) and live workflows (4). These are implementation checks, not a measurement of detection accuracy or reviewer agreement. An earlier live attempt timed out; the retry completed. Full results and inputs are included in GitHub.

## 2. Oversight Challenge

Reviewers must identify which projects warrant additional review from a large volume of publicly available records.

Public records become more useful when the selection method can be repeated.

The server turns available records into documented review indicators.

One disaster shows the scale: the DR-4611 review queue was built from 3,648 public funded-project records. Two needs follow from it. Prioritization means deciding where to look first. Evidence reconstruction means showing another reviewer exactly why.

## 3. Current Workflow Problem

Without an encoded method, every review starts from raw records. The steps below are illustrative of manual preparation, not a measurement of any team’s process.

| Step | What happens without an encoded method |
| --- | --- |
| 1. Pull records | Scope is chosen by hand for each question. |
| 2. Compute comparisons | Calculations live in personal spreadsheets. |
| 3. Decide what to review | The method behind the choice is not recorded. |
| 4. Hand off | The next reviewer rebuilds the evidence. |

The result is prioritization that is hard to repeat and hard to defend.

## 4. Innovation: Encoded Oversight

The client selects an action and supplies its scope.

FEMA Oversight MCP executes the documented rule.

The server returns structured evidence for the client to present:

- evaluates indicators

- assembles evidence

- documents methods

- explains limitations

- prepares reviewer-ready outputs

The server adds deterministic calculations and an inspectable evidence contract to public-data retrieval. The same records and parameters reproduce the same calculations; timestamps and refreshed source data can change.

## 5. Architecture

Reviewer Question  >  MCP Tool  >  Evidence Generation  >  Validation  >  Recommendation Package  >  Human Reviewer

| Stage | What happens |
| --- | --- |
| Reviewer Question | A reviewer asks in plain language through any MCP-capable SI client. |
| MCP Tool | The client selects a goal-based tool. Inputs are validated before tool logic runs. |
| Evidence Generation | Code retrieves OpenFEMA records and applies the documented review rule. |
| Validation | Briefs resolve identity and re-check the rule. Screens and queue report retrieval scope and cap status. |
| Recommendation Package | Ranked results or an evidence brief with source, method, scope and limitations. |
| Human Reviewer | Reviews the package and makes every decision. |

Controls: Read-only; fixed source; traceable outputs; documented limitations.

### Code organization

Modules separate data models, tool definitions and data access, so each component can be read and tested on its own. Dependencies run one way: tools depend on indicators, data access, methodology and schemas. The review rules have no dependency on MCP or HTTP.

| Module | Responsibility |
| --- | --- |
| schemas/inputs.py | One validated Pydantic request model per tool |
| schemas/outputs.py | Result models published as each tool’s output schema |
| data_access.py | What to fetch, the hardened OpenFEMA client, and the archived-snapshot source |
| indicators.py | The three review rules as pure functions, with no I/O |
| methodology.py | Methodology cards, limitations and the provenance builder |
| errors.py | Stable error codes with hints and retryable flags |
| tools/screening.py, tools/review.py | The six agent-facing review actions |
| server.py | The only place components are wired together |

## 6. Tool Inventory

6 read-only tools, 2 resources (fema-pa://provenance, fema-pa://methodology) and 1 prompt (disaster_review). The full inventory is in Appendix A.

| Tool | Reviewer goal |
| --- | --- |
| build_review_queue | Where should I start in this disaster? |
| screen_category_cost_outliers | Which projects cost far above the retrieved category baseline? |
| find_repeated_worksheet_groups | Is the same project listed more than once? |
| screen_cost_share_ratios | Which federal shares fall outside the expected band? |
| explain_review_indicator | How was this produced, and what can't it tell me? |
| prepare_evidence_brief | Give me the evidence package for this worksheet. |

Every tool: readOnlyHint true, destructiveHint false, idempotentHint true; one validated Pydantic request model (extra fields forbidden); USE WHEN and DO NOT USE guidance; a published output schema.

## 7. Product Walkthrough

### 7.1 Reviewer Question

| Reviewer asks | Tool call | Result |
| --- | --- | --- |
| “Where should I start in Hurricane Ida (DR-4611)?” | build_review_queue<br>{"params":{"state_code":"LA","disaster_number":4611,"limit":5}} | Ranked queue from 3,648 records |
| “Which utility projects cost far above the retrieved category baseline?” | screen_category_cost_outliers<br>{"params":{"state_code":"LA","disaster_number":4611,"damage_category_code":"F"}} | 115 Category F records; 3 recommended |
| “Show me the evidence for the largest one.” | prepare_evidence_brief<br>{"params":{"pw_number":1725,"disaster_number":4611,"applicant_id":"109-99109-00","indicator":"category_outlier"}} | Evidence package for PW 1725 |

### 7.2 Prioritized Output

The November 19 DR-4611 queue used 3,648 records and did not reach its retrieval cap. It ranks worksheets by distinct indicator count, then project amount. The tool reports 55 category-outlier rows, 134 repeated-title groups and 1,510 cost-share rows. These totals have different units and can overlap; they must not be added. The top five entries each have three distinct indicator types. Source titles are preserved in the saved live MCP demonstration.

| Project | Indicator count | Applicant ID | Traceability status |
| --- | --- | --- | --- |
| PW 966 · NCS-WRAP AROUND SERVICES 90%  COST SHARE | 3 of 3 | 000-U04DB-00 | Source · scope · method · limits |
| PW 2106 · Facilities Mold Remediation (100% cost share) | 3 of 3 | 051-U415A-00 | Source · scope · method · limits |
| PW 732 · EMAC 100% COST SHARE | 3 of 3 | 000-U04DB-00 | Source · scope · method · limits |
| PW 2105 · Facilities Mold Remediation (90% cost share) | 3 of 3 | 051-U415A-00 | Source · scope · method · limits |
| PW 1900 · IDA CAT-B | 3 of 3 | 000-UEK3R-00 | Source · scope · method · limits |

Several titles state an adjusted 90% or 100% cost share. The package asks the reviewer to confirm the authorized share; it does not judge it.

### 7.3 Evidence Package

PW 1725 · Houma Power Plant. Disaster 4611 / applicant 109-99109-00 / PW 1725 · Terrebonne Parish, Louisiana.

| Package field | Content |
| --- | --- |
| Recommendation | Review first: the largest Category F (Public Utilities) cost outlier in DR-4611. |
| Supporting evidence | Project amount $149,603,170.72, 7.73 standard deviations above the Category F mean. Federal share obligated $134,642,853.65, equal to total obligated. |
| Method | (project amount − category mean) ÷ category standard deviation; recommended at 3.0 or more. Re-checked against current peers when the brief is prepared. |
| Source | OpenFEMA PA Funded Projects Details v2. Brief baseline: 115 Category F records for DR-4611, described in indicator_check.baseline. The separate category screen reports structured scope and did not reach its cap. |
| Limitations | Compared with the retrieved category, not engineering peers. Large infrastructure projects are expected to be high. OpenFEMA data is not FEMA’s official financial system. |
| Reviewer handoff | Confirm scope of work and cost estimate in the project record, and confirm the authorized cost share. The reviewer decides. |

The system recommends projects for review; reviewers make all decisions.

## 8. Evidence Traceability

Data-bearing screens and the queue return source, rule, limitations and structured retrieval scope. The evidence brief adds source records, the re-check, a method card and analyst next steps. Its baseline scope is in text. The static explanation tool returns a methodology card and performs no retrieval.

- Screens and queue: provenance and data_scope

- Brief: source_records, indicator_check and methodology

- Brief: analyst_next_steps and provenance

- Explanation: static rule and limitations

- Client: presents returned evidence for human review

The schemas differ by action. No claim is made that every tool has a data_scope block or a retrieval timestamp. v1.1 does not control the client model’s final prose and does not implement electronic reviewer approval.

## 9. How Calculations Add to Retrieval

| Retrieval task | FEMA implementation |
| --- | --- |
| Fetch public records | Use one fixed OpenFEMA endpoint |
| Select the comparison | Apply documented rule and parameters |
| Compute the result | Run deterministic Python calculations |
| Explain the output | Return typed evidence and limitations |

Recommendations are computed from records by documented rules, not composed from retrieved text.

## 10. How the Queue Supports Review

| Reviewer need | Server support |
| --- | --- |
| Choose where to start | Queue ranked by indicator count and project amount |
| Understand the reason | Every queue entry lists its indicator reasons |
| Inspect one project | Brief with records and default-rule re-check |
| Decide what follows | Human judgment outside the server |

## 11. Evaluation Results

Current run 20261119T134625Z: 37 of 37 evaluation checks passed. Separately, 63 of 63 unit and contract tests passed, with lint and formatting clean. The groupings below organize the checks for presentation; they are not precision, recall or operational success rates.

| Objective | Checks | Outcome |
| --- | --- | --- |
| Calculation agreement | 11 / 11 | 3 controls, 6 repeatability checks, 2 live screen comparisons. |
| Tool contracts | 5 / 5 | 5 tool contract assertions; not a field-by-field provenance audit. |
| Errors and workflows | 21 / 21 | 19 error cases plus brief and queue workflow checks. |
| Total | 37 / 37 | All checks passed |

### Testing methodology

The harness calls real tools through an in-memory MCP client. Three controls compare results with independent SQLite calculations and recorded v1.0 outputs on identical archived snapshots. Five checks inspect contracts, nineteen exercise errors, six check repeated outputs, and four use live OpenFEMA. Two live screens are compared with independent direct queries; the brief check verifies its rule was met and the queue check verifies that it builds. The latter two are workflow assertions, not independent validation of every field.

### Performance

Run 20261119T134625Z: snapshot in-process medians range from 7.2 to 100.8 ms across six tools, ten calls per tool. Four individual live calls took 0.44 seconds (category), 0.26 seconds (repeats), 1.95 seconds (brief) and 13.95 seconds (queue). These observations do not establish uptime, throughput or a latency guarantee.

### Lessons learned

- A control must be able to fail. The earlier November 18 report describes a tampering exercise. It is historical supporting evidence and is not an extra check in the current 37.

- A worksheet number is not a complete identity. Use disaster, applicant and PW together. The brief reports ambiguity when an applicant is not specified and several match.

- Repeated titles can describe routine work. DR-4827 returned 86 groups, including two same-wording groups. The grouping counts retrieved rows and does not deduplicate upstream duplicates; reviewers must inspect the distinct worksheet list.

- An indicator is not a finding. In DR-4611 the cost-share screen returns 1,510 indicators, and several top titles state an adjusted 90% or 100% share. Every result states that authorized shares are not verified.

- Errors should guide recovery. Validation errors name invalid fields. Expected domain and upstream errors return a code, a hint and a retryable flag. Unexpected details are masked.

### Recommendations

- Measure client-side tool selection with reviewers during the pilot.

- Add declaration-specific authorized cost-share references to the cost-share screen.

- Match peers by project size, applicant type and geography.

## 12. Governance Controls

- Read-only architecture

- Fixed public source

- Transparent evidence chain

- Documented limitations

- Human review requirement

Implementation details and security considerations are in Appendix D.

SI assists. Humans decide.

## 13. Pilot

Proposed scope: One declaration; one authorized review team; retrospective review preparation from public funded-project records; compared with the team’s existing preparation process.

| Measure | Definition |
| --- | --- |
| Evidence reconstruction effort | Time for a second reviewer to reconstruct why a project was recommended. |
| Reviewer agreement | Share of recommendations that reviewers judge warranted for review, recorded by reviewers. |
| Evidence completeness | Share of packages with source, method, scope, limitations and identity all present and correct. |
| Recommendation transparency | Whether a reviewer can state why each project was recommended from the package alone. |

Proposed pilot. No savings, return on investment, adoption, reviewer agreement or model-selection improvement is measured. Reviewer disposition remains outside this server.

## 14. Reusable Pattern

### Reusable components

| Component | What transfers |
| --- | --- |
| MCP architecture | Goal-based, typed, read-only tools over one data client, with one-way module dependencies. |
| Provenance framework | Typed action-specific outputs. Screens and queue include structured scope; briefs include source records and baseline text. |
| Governance controls | Read-only design, fixed source origin, input validation, masked errors, human review. |
| Recommendation framework | Review queue, single-record evidence brief and methodology cards. |

### Program-specific components

| Component | What a new program supplies |
| --- | --- |
| Datasets | The program’s public source and its record identity. |
| Indicators | The review rules that fit the program. |
| Methodologies | Documented and independently validated calculations and limits. |

Transferability comes from the architecture: a new program replaces the data adapter and the review rules, and keeps the evidence contract.

## 15. Judging Criteria Map

| Criterion | Where the evidence is |
| --- | --- |
| Code readability and maintainability | Section 5, Code organization; Appendix A |
| Server performance and reliability | Section 11; Appendix B (37 of 37 checks; 63 of 63 tests) |
| Adherence to MCP design principles | Section 6; Appendix A (Pydantic inputs, USE WHEN / DO NOT USE, output schemas, goal-based tools) |
| Innovation | Section 4; Sections 9 and 10 |
| Mission alignment | Sections 2, 13 and 14 |
| Presentation | Section 7, Product Walkthrough; judges deck |

## Appendix A. Tool Inventory

| Tool | Reviewer goal | What it does | Required inputs |
| --- | --- | --- | --- |
| build_review_queue | Where should I start in this disaster? | Runs all three review rules in one retrieval, merges results by worksheet identity and ranks worksheets by indicator count, listing every reason. | state_code, disaster_number |
| screen_category_cost_outliers | Which projects cost far above the retrieved category baseline? | Builds the category baseline, computes standard deviations above the mean, ranks results and records scope. | damage_category_code (A-G), plus state and/or disaster |
| find_repeated_worksheet_groups | Is the same project listed more than once? | Normalizes titles, groups worksheets, labels each group as same wording or numbered series, and lists closest matches first. | state and/or disaster |
| screen_cost_share_ratios | Which federal shares fall outside the expected band? | Computes federal-share ratios, marks results below or above the band, and states that authorized shares are not verified. | state_code |
| explain_review_indicator | How was this produced, and what can't it tell me? | Returns the methodology card the tools execute against. Makes no data call. | indicator |
| prepare_evidence_brief | Give me the evidence package for this worksheet. | Resolves record identity, re-runs the triggering rule against current peers, and adds the method card and next review steps. | pw_number, disaster_number, indicator |

Every tool: readOnlyHint true, destructiveHint false, idempotentHint true; one validated Pydantic request model (extra fields forbidden); USE WHEN and DO NOT USE guidance; a published output schema.

Resources: fema-pa://provenance and fema-pa://methodology. Prompt: disaster_review(state_code, disaster_number).

## Appendix B. Evaluation Methodology

### Calculation agreement 11 of 11 checks

- Controls 3/3: tool output equals an independent SQLite implementation on identical archived OpenFEMA snapshots (238 = 238; 74 = 74; 3 = 3)

- Stability 6/6: 10 identical calls per tool return identical results

- Live 2/2: Louisiana DR-4611 Category F (115 records; PWs 1725, 1679, 5757 at 7.73, 4.75, 3.29 standard deviations) and North Carolina DR-4827 repeated groups (86 = 86; 3,107 records) match direct OpenFEMA queries written independently of the server

### Tool contracts 5 of 5 checks

- Exact tool set registered

- All tools read-only

- USE WHEN and DO NOT USE guidance in every description

- Every input field described

- Every tool publishes its own typed output schema. Data scope is present in screens and queue, not every tool.

### Errors and workflows 21 of 21 checks

- Error handling 19/19: fifteen invalid-input or domain cases plus four simulated upstream failures. Invalid inputs name fields; expected domain and upstream errors include codes and recovery guidance.

- Live review queue: DR-4611 queue built from 3,648 records, not truncated

- Live evidence brief: PW 1725 indicator re-check met (7.73 standard deviations; threshold 3.0)

### Additional checks

- 63 of 63 unit and contract tests passed on November 19. Lint and formatting checks pass.

- Historical tampering exercise described in the November 18 report; not counted in the current 37 checks.

- Current snapshot in-process medians 7.2-100.8 ms. Four live calls 0.26-13.95 seconds. See the complete per-tool timings in the machine-readable result.

### Claims register

| Claim | Value | Source |
| --- | --- | --- |
| Evaluation checks | 37 of 37 passed | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| Unit and contract tests | 63 of 63 passed; lint and format clean | eval/results/20261119-local/pytest.xml and checks.json |
| Calculation agreement | 11 of 11 | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| Tool contracts | 5 of 5 | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| Errors and workflows | 21 of 21 | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| Tool inventory | 6 tools, 2 resources, 1 prompt | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| DR-4611 queue | 3,648 rows; 55 outlier rows / 134 title groups / 1,510 cost-share rows. Units differ and overlap. | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| DR-4611 Category F | 115 records; PWs 1725, 1679, 5757 at 7.73, 4.75, 3.29 | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| PW 1725 | $149,603,170.72; 7.73 standard deviations; re-check met | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| DR-4827 repeated groups | 86 groups, 2 same wording, 3,107 records | Current run 20261119T134625Z; eval/results/20261119-live-attempt/summary.json |
| Queue project titles and PW 1725 obligations | As published | Live MCP demonstration recorded November 19 2026; demo.json |

## Appendix C. Evidence Examples

| Example | Tool | Evidence returned |
| --- | --- | --- |
| DR-4611 review queue | build_review_queue | 3,648 rows, cap not reached. Top five have three indicator types. Totals: 55 outlier rows, 134 title groups, 1,510 cost-share rows. Units differ and overlap. |
| DR-4611 Category F screen | screen_category_cost_outliers | 115 records. PWs 1725, 1679 and 5757 at 7.73, 4.75 and 3.29 standard deviations; matches an independent direct query. |
| PW 1725 evidence brief | prepare_evidence_brief | Houma Power Plant, $149,603,170.72, 7.73 standard deviations; indicator re-check met against 115 Category F peers. |
| DR-4827 repeated worksheets | find_repeated_worksheet_groups | 86 groups over 3,107 records; 2 with the same wording listed first; matches an independent direct query. |

## Appendix D. Governance Details

| Control | Implementation |
| --- | --- |
| Read-only architecture | All six tools carry readOnlyHint true and destructiveHint false. No write, approve or disposition tool exists. |
| Fixed public source | One public source, OpenFEMA PA Funded Projects Details v2, reached through a fixed origin by a hardened HTTP client. |
| Transparent evidence chain | Typed schemas differ by action. Screens and queue include provenance and data scope; briefs include provenance and baseline text; explanations return static method cards. |
| Documented limitations | Each indicator has a methodology card with its rule, threshold and limits, served by explain_review_indicator and embedded in every brief. |
| Human review requirement | Outputs are review recommendations, never findings. The system recommends projects for review; reviewers make all decisions. |

### Security considerations

| Consideration | Implementation |
| --- | --- |
| Input validation | Each tool accepts one Pydantic request model with extra fields forbidden. Invalid input is rejected before tool code runs, and the error names the field. |
| Injection resistance | OData injection attempts in state and applicant inputs are rejected (verified in the error-handling suite). |
| Error masking | Expected domain and upstream errors include a code, hint and retryability. Pydantic errors name the invalid field. Internal exceptions are masked. |
| Fixed data origin | The data client uses a fixed OpenFEMA HTTPS origin and dataset path, with redirects and environment proxies disabled. |
| Least privilege | Read-only tools only. No source credentials are required. Public records may contain applicant and project names. Do not treat public availability as proof that no personal information is present. |

Read-only annotations state intent; access in any deployment is enforced by that deployment’s controls.

## Appendix E GSA Template Adaptation

| Component | Template pattern | FEMA implementation |
| --- | --- | --- |
| Entry and wiring | main.py and src/example_server/app.py | main.py and src/fema_oversight/server.py |
| Validated models | models.py | schemas/inputs.py and schemas/outputs.py |
| Agent actions | tools/ with register functions | tools/screening.py and tools/review.py |
| API and rule logic | utils.py and config.py | data_access.py, indicators.py and methodology.py |
| Testing and packaging | tests, eval, uv, deployment recipes | 63 tests, 37-check evaluation, pinned lock and sandbox configs |

GSA template revision f39249f17683. File mapping: docs/GSA_TEMPLATE_ALIGNMENT.md. GitHub fork parent: phebeong/2026-HACKATHON. The original TTS MIT notice is retained.
