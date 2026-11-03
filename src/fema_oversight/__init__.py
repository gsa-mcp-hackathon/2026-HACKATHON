"""FEMA Public Assistance Evidence & Oversight Graph — MCP server package.

Transforms open FEMA Public Assistance data into traceable, explainable,
analyst-ready oversight intelligence. Every tool returns REVIEW INDICATORS on
public aggregate data, never findings; a human analyst makes every decision.

Architecture guide:
* ``clients.py`` — fixed-origin OpenFEMA access, caching, metadata
* ``models.py`` — strict Pydantic schemas for MCP tools
* ``tools/`` — goal-oriented analyst actions
* ``middleware.py`` — structured errors and rate limiting
* ``resources/`` — provenance, methodology, and guardrails published to clients
"""

__version__ = "0.1.0"
