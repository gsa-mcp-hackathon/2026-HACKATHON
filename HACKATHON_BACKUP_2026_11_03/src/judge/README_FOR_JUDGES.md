# FEMA Evidence & Oversight Graph: Read This First

**Trusted oversight infrastructure for AI agents using evidence-backed review recommendations.**

Phebe Arouni & Tom Jacobson | Dataset Access track | Submission of October 29, 2026 | App page and repeat rule updated November 2, 2026; repeat example and side-by-side view updated November 3, 2026; this page updated November 4, 2026 to match the final submission package (see "What changed and when")

You do not need any technical knowledge to judge this entry. Read the next part (1 minute), then try the app (2 minutes).

## In plain English (1 minute)

**The problem.** After a hurricane or flood, FEMA's Public Assistance program obligates billions of dollars to repair roads, utilities, schools and other public facilities. FEMA publishes these projects on OpenFEMA as hundreds of thousands of records. An oversight reviewer (a FEMA analyst, an Inspector General auditor, a congressional staffer) cannot read them all. They need to know which projects to review first, and why.

**The trust gap.** An AI model without access to the data cannot answer exact questions about these records. When it narrates on its own, it can add statements the data does not support. We measured both. In oversight, an answer you cannot trace back to a federal record cannot be used.

**What we built.** Trusted oversight infrastructure for AI agents. You ask a question in plain English. The AI has one job: choosing which of five read-only tools to use. The tools pull **live FEMA records**, apply a **published rule**, and do **all the math**. The answer you see is built from the tools' results, not written freely by the AI. Every answer shows:

* **What was returned for review**, with the exact FEMA project records it came from
* **How it was calculated**, in plain terms
* **What it does not tell you** (a review indicator is a reason to look, not a conclusion)
* **Where the data came from and when it was retrieved**

**AI points. Evidence proves. People decide.** The tools only read data. They cannot change, approve, or deny anything. A person makes every determination.

**The proof.** On the questions shown in the walkthrough notebook, the AI got the exact counts right **10 out of 10 times with our tools, and 0 out of 10 without them**. Every count our tools produce was checked against a separate calculation and matched exactly. On November 4, 2026 we re-ran the Hurricane Ida example against live FEMA data, and a separate direct query returned the same three projects.

## Try the app yourself (2 minutes)

1. Open **https://2026h-7474654188777746.aws.databricksapps.com** in your browser. If asked, sign in with your Databricks workspace login.
2. The page is titled **FEMA Disaster Spending Check**. It opens with three short boxes: the problem, what the app checks, and why the evidence matters.
3. Click one of the three large question cards. The review starts right away:
   * **Are any road and bridge projects unusually expensive?** Hurricane Ian, Florida, 2022 (disaster 4673)
   * **Are any utility repairs unusually expensive?** Hurricane Ida, Louisiana, 2021 (disaster 4611)
   * **Is the same project listed more than once?** Tropical Storm Helene, North Carolina, 2024 (disaster 4827)
4. Watch the four progress steps. Step 2, "Running checks on live FEMA data", usually takes 5 to 15 seconds, and a timer shows the time so far. The app reports back only when the whole review is finished, so that step has no finer progress.
5. Read the result from top to bottom:
   * **Headline**: one sentence saying what was found
   * **Four tiles**: **Records checked** (FEMA records downloaded and tested), **Flagged for review**, **Examples shown** (how many of the flagged items are listed on the page), and **Download completeness** (whether the per-check record limit was reached)
   * **Two charts**, drawn only from the returned results
   * **The rule, in plain English** and **What a flag does not mean**
   * For the utility repairs card, an **Evidence packet**: one project's original FEMA record, ready for a reviewer
   * For the listed-twice card, **Look inside each group**: click a group to see its worksheets side by side. A checklist shows what they have in common (same applicant, disaster, type of work and title words), a second list shows the only differences, and the part of each title that changes is highlighted. Each group is labelled **Same wording** (only capitals, spacing or dashes differ), **Numbered series** (one number changes, such as Site 1 and Site 2) or **Several differences** (for example different street numbers), and the closest matches are listed first.
   * **For reviewers and technical judges**: expandable sections with the written summary, every step the app ran, the raw records and the raw response
   * **Download evidence (JSON)**: saves the full record so anyone can check it later

(Optional) Under the cards, **Or type your own question** lets you ask something else.

**What you should see** (live results checked on November 2, 2026, on November 3 for the listed-twice card, and on November 4 for the utility repairs card; FEMA updates its data daily, so numbers can change):

| Card | Headline |
|---|---|
| Expensive road and bridge projects | 3 of 179 projects cost far more than similar projects. The largest is about 25 times the average. |
| Expensive utility repairs | 3 of 115 utility projects cost far more than similar projects. The largest is about $149.6 million, about 31 times the $4.8 million average. |
| Listed twice | 86 groups of near-identical project titles found in 3,099 records checked. The closest match is listed first: "Div 13 Yancey" and "DIV 13 - Yancey", two large road-repair worksheets from the same applicant ($1.38 million and $1.64 million estimated), whose titles differ only in capitals and a dash. |

**What to notice.** Every number on the page comes from the check results, and the raw records are one click away. The page keeps "records checked", "flagged" and "shown" separate, so a short example list is never mistaken for the full count. It says what a flag does not prove. For repeated worksheets, titles are compared after ignoring capitals, punctuation and numbers, and each group can be opened to compare its worksheets side by side, with what they share, what differs, and each worksheet's cost. A close match is a reason to compare the worksheets, not a determination that anything was paid twice. Many numbered series are legitimate (separate buildings, sites or phases), and the page says so.

### What changed and when

On November 2, 2026 we made two changes:

* **The web page** was redesigned so results are easier to read (the three question cards above, summary tiles, charts).
* **The "listed twice" rule** changed. FEMA titles are almost never repeated exactly: the October 29 rule (exact same title) found no groups in 11 Florida disasters or in a 140,000-record national sample. The rule now compares titles after ignoring capitals, punctuation and numbers, so "Site 1" and "site #2" match.

Because the rule is code, the code fingerprint changed, so we re-ran every check on the new code. Later on November 2 we also shortened the data caveat text and added each project's name to the "unusually expensive project" chart. Neither change affects which projects are flagged or how many. We then re-ran every check on the final code. The recorded run (`20261102T152007Z`, code fingerprint `9cdad51e...`) passed all of them: 71/71 automated tests, lint, the independent calculations (238 = 238 cost-share flags; 74 = 74 repeated groups; 3 = 3 road projects), the AI tool-choice (15/15) and workflow tests (3/3 and 3/3), and the with/without-tools comparison (15/15 vs 0/15). The earlier November 2 run (`20261102T120900Z`, fingerprint `936a4788...`) gave the same results and is kept in the zip for reference.

The October 29 zip in this folder, its fingerprint (`f70d0a80...`) and its recorded run describe the October 29 code. The updated packet, `FEMA_Hackathon_Submission_2026-11-02.zip`, holds the new code, the new recorded run, the updated deck and video, and updated judge documents (see `docs/NOVEMBER_2_UPDATE.md` inside it). It is stored in the volume `/Volumes/users/phebe_arouni/hackathon_submissions/20261102/`. One check was not repeated: the hosted-app sign-in smoke test, because the app's sign-in redirect could not be completed from a notebook; the October 29 smoke record remains.

**November 3, 2026 update (live app only).** To make the listed-twice result easier to judge, we added the side-by-side view described above, labelled each group by how closely its titles match, listed the closest matches first, and moved the card to North Carolina disaster 4827, where the closest matches are clearer than in Florida 4673. The rule that decides which worksheets are grouped did not change: Florida 4673 still gives 74 groups and North Carolina 4827 gives 86. This changed the app's code, so the live app is now newer than the November 2 zip and its code fingerprint no longer matches the recorded run. We checked the new code with the 71 automated tests and the lint check (all passed), compared one group's worksheets with FEMA's records directly (they matched) and ran the card's question through the app. We did not repeat the full recorded run. The zip, its fingerprint and its recorded run are unchanged.

**November 4, 2026 update (documents only).** We wrote the final submission package, `2026-HACKATHON/SUBMISSION_FINAL/FINAL_SUBMISSION_PACKAGE.md` in the team workspace. It contains the executive summary, architecture, the step-by-step agent design, tool definitions, the live demo script, the full evaluation and its results, security and governance controls, the replacement slide deck with speaker notes, and answers to likely judge questions. This page now uses the same wording. The final slide deck built from that package is `/Volumes/users/phebe_arouni/hackathon_submissions/20261104/FEMA_Evidence_Oversight_Graph_FINAL_2026-11-04.pptx`, with a PDF copy in the same folder. No app code changed. We re-ran the 71 automated tests and the lint check on the November 2 zip (all passed; its code is identical to our backup copy of the November 2 release). We also re-checked the utility repairs card against live FEMA data with a separate direct query: same 115 records, same $4,802,096.50 average, same 3 projects. The separate query used a slightly different standard-deviation formula (sample instead of population), so it scores the top project 7.70 instead of 7.73; the projects and their order are the same. The hosted app was not re-tested from a notebook, because its sign-in redirect cannot be completed there.

If the app page does not open for you, use the notebook below. It shows the same check results and needs no login.

## Why this entry should win

| Judging criterion | Our answer |
|---|---|
| Technical quality | The AI only chooses tools; code does every calculation; the answer is built from tool results. 71 automated tests pass. Tool results matched a separate calculation every time. |
| Innovation | A step-by-step agent design that limits the AI to choosing tools, can say "no" or "no usable evidence", and always ends with a person. Every answer carries its own evidence chain. |
| Mission alignment | Helps FEMA and oversight reviewers decide where to look first in Public Assistance, with evidence they can defend. |
| Presentation | A two-minute demo: three Hurricane Ida utility projects, the evidence behind each, and the decision handed to a person. |
| Trust | Every answer shows source records, method, limits and retrieval time, and is labelled a review indicator. Only a person makes a determination. |
| Safety | Read-only tools. Bad inputs are rejected with a clear message. Runs behind Databricks sign-in. |
| Honesty | It reports "nothing found" when nothing is found, publishes its known limits, and when we changed a rule we said why and re-ran every check. |

## Want to check our claims? (5 minutes, optional)

1. **Open `00_JUDGES_START_HERE - FEMA Evidence and Oversight Graph Walkthrough`** (the notebook in this folder) and click **Run all**. It needs no setup or passwords and does not change any data.
2. **Read it from top to bottom.** Each step has a short "What this shows" note, then the proof. It covers: the problem, confirming the code is exactly what was submitted, the automated tests, the two live scenarios, guardrails, accuracy checks, and the AI test results.
3. **Look at the Scorecard (Step 10)** at the end. It lists each check as pass or fail and compares it with the recorded run inside the zip it used (November 2 for the new packet).

## Words you may see

| Term | Meaning |
|---|---|
| FEMA Public Assistance | FEMA money paid to states and towns to repair public infrastructure after a disaster |
| OpenFEMA | FEMA's free, public data website |
| Review indicator | A reason for a person to look more closely, based on a published rule. The app shows these under "Flagged for review". It is not a determination; a person decides. |
| Review recommendation | The tools' answer: which records to review first, with the evidence behind them |
| Evidence chain | What travels with every answer: data source, retrieval time, scope, method, record identity (disaster, applicant, project worksheet), limits and review status |
| Project worksheet | FEMA's record for one repair project |
| Category C | FEMA's label for roads and bridges |
| Category F | FEMA's label for utilities, such as power, water and sewer |
| Evidence brief | A one-page package of the source records for one project, for a human reviewer |
| MCP | A standard way for AI assistants to use outside tools. It lets any compatible AI use our five tools. |
| Databricks App | A web application hosted securely inside Databricks |

## What is in this folder

| File | What it is |
|---|---|
| `00_JUDGES_START_HERE - ...` (notebook) | The step-by-step walkthrough. Start here. |
| `FEMA_Hackathon_Submission_2026-10-29.zip` | The submitted code, documents, deck, video and raw evaluation evidence |
| `/Volumes/users/phebe_arouni/hackathon_submissions/20261102/` | November 2 update: `FEMA_Hackathon_Submission_2026-11-02.zip`, plus the updated deck, video and judge brief as separate files |
| `README_FOR_JUDGES.md` | This page |
| `2026-HACKATHON/SUBMISSION_FINAL/FINAL_SUBMISSION_PACKAGE.md` (team workspace) | November 4 final submission package: summary, architecture, demo script, evaluation, controls, replacement deck content and judge Q&A. |
| `/Volumes/users/phebe_arouni/hackathon_submissions/20261104/` | November 4 final deck: `FEMA_Evidence_Oversight_Graph_FINAL_2026-11-04.pptx` (16 slides: 12 main + 4 appendix, speaker notes on every slide, timed demo script in the slide 7 notes) and the same deck as `.pdf`. Built from the final submission package. This replaces the November 2 decks in the zip and in the `20261102` volume folder. |

## Main documents inside the zip (for technical reviewers)

| Path in zip | Read it for |
|---|---|
| `SUBMISSION.md` | Official submission summary and links |
| `docs/JUDGE_BRIEF.md` | One-page brief |
| `presentation/FEMA_Evidence_Oversight_Graph.pptx` / `.mp4` | Earlier deck and captioned walkthrough video (November 2 version; the final deck is in the `20261104` volume folder) |
| `eval/evaluation_documentation.md` | Evaluation method and results |
| `eval/results/20261102T152007Z/` | Raw evidence from the November 2 recorded run (inputs, outputs, model traces); the earlier November 2 run is in `eval/results/20261102T120900Z/` and the October 29 run in `eval/results/20261029T111811Z/` |
| `docs/NOVEMBER_2_UPDATE.md` | What changed on November 2 and the evidence for it |
| `docs/TECHNICAL_DESIGN.md`, `SECURITY.md` | Design and security |
| `docs/LIMITATIONS_AND_ROADMAP.md` | Known limits |

## Headline results (recorded run 20261102T152007Z, re-checked in the notebook)

| Check | In plain words | Result |
|---|---|---|
| Code fingerprint (SHA-256 of source) | The code being judged is exactly the code that was tested | Matches the tested release, `9cdad51e...` |
| Automated tests | Built-in quality checks | 71/71 pass; lint clean |
| Tool output vs. independent SQLite calculation | Our results match a separate calculation done another way | 2/2 exact matches (3 expensive road projects and 74 repeated-title groups flagged) |
| Model picks the correct first tool | The AI chooses the right tool for the question | 8/8 questions |
| Exact counts with tools vs. without tools | Correct numbers with our tools vs. the same AI model with no data access | 10/10 vs 0/10 (without tools, the model declined to answer every time) |
| End-to-end grounded review workflows | Full question-to-evidence runs that work start to finish | 2/2 |
| Live re-check, November 4, 2026 | The utility repairs card still matches a separate direct query of live FEMA data | Same 3 projects out of 115; top project PW 1725, Houma Power Plant, $149.6 million |

The notebook shows the checks for the scenarios the app features. The full recorded run also includes one more screening check that the app no longer features; with it, the totals are 15/15 tool choices, 15/15 vs 0/15 exact counts, 3/3 independent matches and 3/3 workflows (final submission package, Section 12). These results are from small, targeted test sets. They are not general accuracy claims. The tools produce review indicators for a person to review; they do not make determinations.

## Links (workspace login required)

* App (open in a browser): https://2026h-7474654188777746.aws.databricksapps.com (AI tool endpoint at `/mcp`)
* Validation job: `67919837469456`. MLflow experiment `1305734463288268`, recorded run `20261102T152007Z` = MLflow run `ff6c41f62dc04e2c929fea1e08ba3e21` (earlier November 2 run: `23ad3105a83e472da58224d902de53ea`; October 29: `7445e452abfc4cd89896658d4ab7f44a`)
* Public repository: https://github.com/phebeong/2026-HACKATHON (October 29 submission commit `f21fe97`; the November 4 final submission package is on `main` at `SUBMISSION_FINAL/FINAL_SUBMISSION_PACKAGE.md`)
