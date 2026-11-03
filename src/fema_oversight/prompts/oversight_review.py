"""Prompt: fema_oversight_review — disciplined, few-turn analyst guidance."""

from __future__ import annotations

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="fema_oversight_review",
        description="Start a disciplined FEMA PA oversight review for a jurisdiction.",
    )
    def oversight_review(state_code: str) -> str:
        """Return a prompt that frames a careful, review-only oversight pass."""
        return (
            "Assist a FEMA Public Assistance oversight analyst reviewing "
            f"{state_code}.\n\n"
            "Prefer the highest-level tool that matches the question:\n"
            "1. build_oversight_triage_queue - create one ranked "
            "multi-indicator review queue.\n"
            "2. get_cost_share_anomalies - screen federal-share ratios only.\n"
            "3. find_repeated_worksheets - screen possible fragmentation "
            "patterns only.\n"
            "4. detect_category_outliers - screen within-category cost outliers only.\n"
            "5. generate_evidence_brief - package one selected worksheet "
            "for human review.\n"
            "6. explain_risk_indicator - cite the fixed methodology.\n\n"
            "Minimize turns: if the user asks what to review first, start with "
            "build_oversight_triage_queue instead of chaining three detector calls. "
            "These are review indicators, not findings. Never imply wrongdoing. "
            "Relay the source, scope limits, provenance, and methodology. "
            "Authorized cost shares may be legitimate. A human makes every "
            "determination. Public data only; not for official reporting."
        )
