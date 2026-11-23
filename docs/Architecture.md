# Architecture

```text
MCP client
   │ typed request
   ▼
FastMCP server ──► tool registration and content-free telemetry
   │
   ├── schemas/        strict Pydantic request and response contracts
   ├── tools/          agent-facing oversight actions and orchestration
   ├── indicators.py   deterministic, side-effect-free review calculations
   ├── methodology.py  shared rule meaning, provenance, and limitations
   └── data_access.py  fixed-origin OpenFEMA client, retries, limits, short cache
                           │
                           ▼
                    OpenFEMA PA v2
```

Dependencies point inward. Calculation code has no MCP or network dependency. Tools depend on a
`RecordSource` protocol, allowing the same production orchestration to run against immutable
evaluation snapshots. The server is read-only and publishes no approval, enforcement, payment,
or case-management action.

## Reliability boundaries

- Fixed upstream origin and path; redirects and environment proxies are disabled.
- Strict time, record-count, and response-size bounds.
- Three bounded attempts for retryable failures with exponential delay.
- Sixty-second, 128-entry cache with concurrent request coalescing; failures are not cached.
- Pydantic validates every MCP request and response contract.
- Agent-recoverable failures use stable codes; unexpected details are masked.
- Aggregate metrics and structured logs exclude arguments and FEMA records.
