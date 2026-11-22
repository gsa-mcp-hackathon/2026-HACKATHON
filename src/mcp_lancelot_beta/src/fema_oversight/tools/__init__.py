"""Agent-facing tools.

Each tool is built around an analyst goal, not an API endpoint:

==============================  ==================================================
Tool                            Analyst goal
==============================  ==================================================
build_review_queue              "Where should I start in this disaster?"
screen_category_cost_outliers   "Which projects cost far more than similar work?"
find_repeated_worksheet_groups  "Is the same project listed more than once?"
screen_cost_share_ratios        "Which federal-share percentages look unusual?"
explain_review_indicator        "How was this result produced, and what are its limits?"
prepare_evidence_brief          "Give me the evidence package for this worksheet."
==============================  ==================================================

Every tool is read-only. Each module exposes ``run_*`` coroutines (pure tool
logic, callable directly by tests and evaluation) and a ``register`` function
that publishes them on a FastMCP server.
"""

from fema_oversight.tools import review, screening

__all__ = ["review", "screening"]
