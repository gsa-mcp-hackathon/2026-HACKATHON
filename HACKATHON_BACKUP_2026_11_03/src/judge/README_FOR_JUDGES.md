# FEMA Evidence & Oversight Graph: Read This First

Phebe Arouni & Tom Jacobson | Dataset Access track | Submission of October 29, 2026 | App page and repeat rule updated November 2, 2026 (see "About the live app version")

You do not need any technical knowledge to judge this entry. Read the next part (1 minute), then try the app (2 minutes).

## In plain English (1 minute)

**The problem.** After a hurricane or flood, FEMA pays billions of dollars to rebuild roads, schools, and other public buildings. FEMA publishes these projects online as hundreds of thousands of records. An oversight reviewer (an auditor, an inspector general, a congressional staffer) cannot read them all. They need to know which projects deserve a second look and why.

**The risk with AI.** You could ask a chatbot. But chatbots often make up numbers, and they cannot show where an answer came from. In government oversight, an answer you cannot check is useless.

**What we built.** An assistant that **does not guess**. You ask a question in plain English. Behind the scenes, the AI does not answer from memory. It uses five checking tools that pull the **real, live FEMA records** and run simple, published rules on them. Every answer shows:

* **What was found**, with the exact FEMA project records it came from
* **How it was calculated**, in plain terms
* **What it does NOT prove** (a flag is a reason to look, not proof of fraud)

A person always makes the final decision. The tool only reads data. It cannot change, approve, or deny anything.

**The proof it works.** When we asked the same 10 questions with and without our tools, the AI got the exact numbers right **10 out of 10 times with our tools, and 0 out of 10 without them**. Every count our tools produce was checked against a separate calculation and matched exactly.

## Try the app yourself (2 minutes)

1. Open **https://2026h-7474654188777746.aws.databricksapps.com** in your browser. If asked, sign in with your Databricks workspace login.
2. The page is titled **FEMA Disaster Spending Check**. It opens with three short boxes: the problem, what the app checks, and why the evidence matters.
3. Click one of the three large question cards. The review starts right away:
   * **Are any road and bridge projects unusually expensive?** Hurricane Ian, Florida, 2022 (disaster 4673)
   * **Are any utility repairs unusually expensive?** Hurricane Ida, Louisiana, 2021 (disaster 4611)
   * **Is the same project listed more than once?** Hurricane Ian, Florida, 2022 (disaster 4673)
4. Watch the four progress steps. Step 2, "Running checks on live FEMA data", usually takes 5 to 15 seconds, and a timer shows the time so far. The app reports back only when the whole review is finished, so that step has no finer progress.
5. Read the result from top to bottom:
   * **Headline**: one sentence saying what was found
   * **Four tiles**: **Records checked** (FEMA records downloaded and tested), **Flagged for review**, **Examples shown** (how many of the flagged items are listed on the page), and **Download completeness** (whether the per-check record limit was reached)
   * **Two charts**, drawn only from the returned results
   * **The rule, in plain English** and **What a flag does not mean**
   * For the utility repairs card, an **Evidence packet**: one project's original FEMA record, ready for a reviewer
   * **For reviewers and technical judges**: expandable sections with the written summary, every step the app ran, the raw records and the raw response
   * **Download evidence (JSON)**: saves the full record so anyone can check it later

(Optional) Under the cards, **Or type your own question** lets you ask something else.

**What you should see** (live results checked on November 2, 2026; FEMA updates its data daily, so numbers can change):

| Card | Headline |
|---|---|
| Expensive road and bridge projects | 3 of 179 projects cost far more than similar projects. The largest is about 25 times the average. |
| Expensive utility repairs | 3 of 115 utility projects cost far more than similar projects. The largest is about $149.6 million, about 31 times the $4.8 million average. |
| Listed twice | 74 groups of near-identical project titles found in 3,964 records checked, for example "Naples Access to Beach - 1" to "- 7". |

**What to notice.** Every number on the page comes from the check results, and the raw records are one click away. The page keeps "records checked", "flagged" and "shown" separate, so a short example list is never mistaken for the full count. It says what a flag does not prove. For repeated worksheets, titles are compared after ignoring capitals, punctuation and numbers, and each group lists its original titles and worksheet numbers. Many numbered series are legitimate (separate buildings, sites or phases), and the page says so.

### About the live app version

On November 2, 2026 we made two changes:

* **The web page** was redesigned so results are easier to read (the three question cards above, summary tiles, charts).
* **The "listed twice" rule** changed. FEMA titles are almost never repeated exactly: the October 29 rule (exact same title) found no groups in 11 Florida disasters or in a 140,000-record national sample. The rule now compares titles after ignoring capitals, punctuation and numbers, so "Site 1" and "site #2" match.

Because the rule is code, the code fingerprint changed, so we re-ran every check on the new code. Later on November 2 we also shortened the data caveat text and added each project's name to the "unusually expensive project" chart. Neither change affects which projects are flagged or how many. We then re-ran every check on the final code. The recorded run (`20261102T152007Z`, code fingerprint `9cdad51e...`) passed all of them: 71/71 automated tests, lint, the independent calculations (238 = 238 cost-share flags; 74 = 74 repeated groups; 3 = 3 road projects), the AI tool-choice (15/15) and workflow tests (3/3 and 3/3), and the with/without-tools comparison (15/15 vs 0/15). The earlier November 2 run (`20261102T120900Z`, fingerprint `936a4788...`) gave the same results and is kept in the zip for reference.

The October 29 zip in this folder, its fingerprint (`f70d0a80...`) and its recorded run describe the October 29 code. The updated packet, `FEMA_Hackathon_Submission_2026-11-02.zip`, holds the new code, the new recorded run, the updated deck and video, and updated judge documents (see `docs/NOVEMBER_2_UPDATE.md` inside it). It is stored in the volume `/Volumes/users/phebe_arouni/hackathon_submissions/20261102/`. One check was not repeated: the hosted-app sign-in smoke test, because the app's sign-in redirect could not be completed from a notebook; the October 29 smoke record remains.

If the app page does not open for you, use the notebook below. It shows the same check results and needs no login.

## Why this entry should win

| Judging question | Our answer |
|---|---|
| Does it use the dataset well? | It works directly on live, public OpenFEMA data. Nothing is copied or pre-cooked. |
| Is it accurate? | Exact numbers 10/10 with tools vs. 0/10 without. All tool results matched an independent check 2/2. |
| Can a reviewer trust it? | Every answer shows its source records, method, and limits. It never calls a flag "fraud". |
| Is it safe? | Read-only. Bad or risky inputs are rejected with a clear message. Runs behind Databricks sign-in. |
| Is it real? | Deployed and running today as a Databricks App, with 71 automated tests passing. |
| Is it honest? | It reports "nothing found" when nothing is found, publishes its known limits, and when we changed a rule we said why and re-ran every check. |

## Want to check our claims? (5 minutes, optional)

1. **Open `00_JUDGES_START_HERE - FEMA Evidence and Oversight Graph Walkthrough`** (the notebook in this folder) and click **Run all**. It needs no setup or passwords and does not change any data.
2. **Read it from top to bottom.** Each step has a short "What this shows" note, then the proof. It covers: the problem, confirming the code is exactly what was submitted, the automated tests, the two live scenarios, guardrails, accuracy checks, and the AI test results.
3. **Look at the Scorecard (Step 10)** at the end. It lists each check as pass or fail and compares it with the recorded run inside the zip it used (November 2 for the new packet).

## Words you may see

| Term | Meaning |
|---|---|
| FEMA Public Assistance | FEMA money paid to states and towns to repair public infrastructure after a disaster |
| OpenFEMA | FEMA's free, public data website |
| Review indicator / flag | A reason for a person to look more closely. Not a finding of wrongdoing. |
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

## Main documents inside the zip (for technical reviewers)

| Path in zip | Read it for |
|---|---|
| `SUBMISSION.md` | Official submission summary and links |
| `docs/JUDGE_BRIEF.md` | One-page brief |
| `presentation/FEMA_Evidence_Oversight_Graph.pptx` / `.mp4` | Deck and captioned walkthrough video |
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
| Exact counts with tools vs. without tools | Correct numbers with our tools vs. a plain chatbot | 10/10 vs 0/10 (without tools, the model declined to answer every time) |
| End-to-end grounded review workflows | Full question-to-evidence runs that work start to finish | 2/2 |

These results are from small, targeted test sets. They are not general accuracy claims. The tools produce review indicators, not findings of fraud or improper payment.

## Links (workspace login required)

* App (open in a browser): https://2026h-7474654188777746.aws.databricksapps.com (AI tool endpoint at `/mcp`)
* Validation job: `67919837469456`. MLflow experiment `1305734463288268`, run `23ad3105a83e472da58224d902de53ea` (October 29: `7445e452abfc4cd89896658d4ab7f44a`)
* Public repository: https://github.com/phebeong/2026-HACKATHON (commit `f21fe97`)
