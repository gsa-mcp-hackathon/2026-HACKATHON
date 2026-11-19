# Technical design and boundaries

The submitted v1.1.0 server is `main.py` and `src/fema_oversight/`. An external MCP client selects the action and arguments. The server contains no LLM, model arithmetic, multi-agent graph, retrieval-augmented text generator or analyst web page.

Flow: external client, validated request, fixed OpenFEMA retrieval, pure calculation, typed result, client display, human review. A client controls its own final wording. v1.1 does not guarantee that a client will quote numbers correctly or suppress unsupported prose.

| Responsibility | File |
| --- | --- |
| Wire components and select transport | `server.py` |
| Define request and output contracts | `schemas/inputs.py`, `schemas/outputs.py` |
| Fetch live or archived records | `data_access.py` |
| Compute deterministic rules | `indicators.py` |
| Share method cards and limitations | `methodology.py` |
| Convert expected failures | `errors.py`, `tools/_registration.py` |
| Execute analyst actions | `tools/screening.py`, `tools/review.py` |

The same tool functions are tested through FastMCP against snapshots. Independent SQLite calculations supply the controls. No official financial system, Grants Manager write access, Unity Catalog query, Do Not Pay integration or disposition workflow is claimed.

Data-bearing screens and queues publish provenance and structured data scope. Briefs publish source records, provenance, method and re-check details, with baseline scope in text. Static explanations publish method cards only. A `possibly_truncated=false` flag means the configured cap was not reached; it is not proof that the upstream dataset includes every real-world project.

The reviewed source fingerprint is unchanged from the November 18 v1.1 report. Source fingerprinting in the evaluation harness now normalizes path separators, so Windows and POSIX produce the same value. The harness also defaults to included fixtures and writes an incomplete live result on expected network failures rather than losing its completed offline evidence.

Next work: measure model selection with the new tool names, validate with analysts, add declaration-specific cost-share references, match richer peers, and supply deployment access and audit controls. None is represented as an implemented or measured outcome.
