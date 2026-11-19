"""FEMA Evidence & Oversight Graph: an MCP server for evidence-backed review.

The package is layered so each part can be read on its own:

* ``schemas.inputs``   what an agent may send (validated Pydantic models)
* ``schemas.outputs``  what an agent gets back (typed, self-describing results)
* ``data_access``      how records are retrieved (OpenFEMA or an archived snapshot)
* ``indicators``       the review rules themselves (pure functions, no I/O)
* ``methodology``      the documented method, limits, and provenance text
* ``tools``            agent-facing actions that combine the layers above
* ``server``           FastMCP wiring: tools, resources, prompt, transport
"""

__version__ = "1.1.0"
