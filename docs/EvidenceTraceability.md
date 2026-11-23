# Evidence traceability

Every data-bearing response includes:

1. Dataset name, publisher, URL, retrieval time, refresh value, and update frequency.
2. The exact rule and thresholds executed.
3. Filters, retrieved-record count, record cap, and truncation signal.
4. Stable worksheet, applicant, and disaster identifiers.
5. Known limitations and an explicit human-review status.

`prepare_evidence_brief` re-runs the triggering rule instead of trusting a prior claim. Methodology
text is defined once in `methodology.py` and reused by screening results, evidence briefs, the
explanation tool, and the MCP methodology resource. This prevents explanatory text from drifting
away from executable logic.
