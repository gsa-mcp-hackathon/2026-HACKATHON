"""Domain knowledge: what each review indicator measures and why.

This module is deliberately free of code paths. It holds the human-readable
"methodology cards" that three different consumers must agree on, word for
word:

* the ``explain_risk_indicator`` tool (what the agent tells an analyst),
* the ``fema-pa://indicators/{indicator}`` resource (what a client can pin), and
* ``grounding.evidence_summary`` (what the deterministic renderer displays).

Keeping the cards in one place means a methodology change cannot silently
diverge between the tool an LLM calls and the summary a human reads.

Framing rule for every string below: outputs are REVIEW INDICATORS on public
aggregate data, not findings. Nothing here detects, proves, or alleges fraud,
waste, or abuse.
"""

from __future__ import annotations

# Appended to every tool response. Phrased so it survives being quoted out of
# context by an LLM: it names what the output is NOT, as well as what it is.
REVIEW_CAVEAT = (
    "Review indicator on public aggregate data. Not a finding; does not allege "
    "fraud, waste, or abuse. A human analyst makes the determination."
)

# FEMA Public Assistance categories of work. A-B are emergency work, C-G are
# permanent work. Category Z (management costs) is administrative and is
# intentionally excluded from cost-outlier screening: its amounts are
# formula-driven, so a statistical baseline would be meaningless.
DAMAGE_CATEGORY_NAMES: dict[str, str] = {
    "A": "Debris Removal",
    "B": "Emergency Protective Measures",
    "C": "Roads and Bridges",
    "D": "Water Control Facilities",
    "E": "Public Buildings and Equipment",
    "F": "Public Utilities",
    "G": "Parks, Recreational and Other Facilities",
}

# Static, auditable methodology cards (the "show your work" layer).
INDICATOR_METHODOLOGY: dict[str, dict[str, str]] = {
    "cost_share_anomaly": {
        "name": "Cost-share anomaly",
        "methodology": (
            "Compares each project's federal share ratio "
            "(federalShareObligated / totalObligated) against an expected band. "
            "FEMA Public Assistance is normally a 75% federal share, but some "
            "declarations are authorized at 90% or 100% by law."
        ),
        "calculation": (
            "ratio = federalShareObligated / totalObligated; flag if ratio < "
            "low or ratio > high."
        ),
        "thresholds": (
            "Default band 0.70-0.95; projects below a minimum total obligated "
            "are ignored to cut noise."
        ),
        "limitations": (
            "Higher statutory shares are expected, not anomalies. Review required."
        ),
    },
    "repeated_worksheet": {
        "name": "Repeated / fragmentation pattern",
        "methodology": (
            "Groups project worksheets by disaster, applicant, application title, and "
            "damage category; flags groups at or above a repeat threshold as a "
            "potential fragmentation or duplication pattern."
        ),
        "calculation": (
            "GROUP BY disasterNumber, applicantId, applicationTitle, "
            "damageCategoryCode HAVING COUNT(*) >= min_repeat_count."
        ),
        "thresholds": "Default min_repeat_count = 2.",
        "limitations": (
            "Repeated titles are frequently legitimate (phased work, multiple "
            "sites). Review signal only."
        ),
    },
    "category_outlier": {
        "name": "Within-category cost outlier",
        "methodology": (
            "Computes the mean and standard deviation of projectAmount within a "
            "damage category, then flags projects a set number of standard "
            "deviations above the category mean. The baseline uses only the "
            "retrieved subset within the selected filters. Supply a disaster "
            "filter for a declaration-specific baseline; declaration type, "
            "project scale and geography are not otherwise matched."
        ),
        "calculation": (
            "sigma_above = (projectAmount - category_mean) / category_stddev; "
            "flag if >= sigma_threshold."
        ),
        "thresholds": "Default sigma_threshold = 3.0.",
        "limitations": (
            "Large, legitimate projects (major infrastructure) can be high "
            "outliers. Review required."
        ),
    },
}

# How the triage tool explains convergence. Kept beside the per-indicator
# cards because it is the same kind of artefact: a published, fixed rule.
TRIAGE_METHODOLOGY = (
    "Runs all three indicator rules over ONE retrieval of the jurisdiction's "
    "records, then joins the flags on project identity (disasterNumber, "
    "applicantId, pwNumber). Queue priority = number of distinct indicators "
    "that fired on the same project (convergence), then federal dollars "
    "obligated. Convergence raises review priority only; it is not evidence "
    "of wrongdoing, and a single-indicator project may still merit review."
)
