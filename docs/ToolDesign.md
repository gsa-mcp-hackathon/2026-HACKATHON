# Tool design

The six tools represent analyst goals rather than OpenFEMA endpoints.

| Tool | User goal | Why it is not an API wrapper |
| --- | --- | --- |
| `build_review_queue` | Decide where to begin within a disaster | Runs three indicators, merges evidence, and ranks worksheets |
| `screen_category_cost_outliers` | Find unusually costly work among comparable projects | Builds a scoped statistical baseline and explains it |
| `find_repeated_worksheet_groups` | Find potentially related worksheets | Normalizes titles and groups by applicant, disaster, and category |
| `screen_cost_share_ratios` | Find shares outside an analyst-selected band | Computes ratios, applies materiality, and supplies policy cautions |
| `prepare_evidence_brief` | Assemble traceable evidence for one worksheet | Re-fetches the record, rechecks the rule, and returns next steps |
| `explain_review_indicator` | Understand a rule without querying data | Returns the same methodology object used by the executing tools |

Every tool has a strict Pydantic input and output model. Descriptions state when to use the tool,
when not to use it, required scope, ranking behavior, and decision limits. All data tools declare
read-only, non-destructive, idempotent, open-world annotations.
