# Security and operating limits

This is a sandbox prototype over public data. The code provides six read-only actions and no approve, change, delete or disposition action. MCP annotations describe tool intent; they do not implement authorization.

## Implemented controls

- Pydantic request models reject unknown fields and invalid ranges before tool logic runs. Scope strings are constrained and OData literals are escaped.
- The OpenFEMA client uses a fixed HTTPS origin and dataset path, disables redirects and environment proxies, sets a 30-second HTTP timeout, and stops responses above 20 MB. It retrieves at most 10,000 records per request, with smaller tool-specific caps.
- Expected domain and upstream errors have stable codes, hints and retryable flags. Pydantic validation errors name the invalid field. Unexpected internal errors are masked by FastMCP.
- No data-source API keys are required. Secret-bearing `.env` files are ignored. Public records can still contain applicant and project names; do not describe all outputs as free of personal information.

## Deployment responsibilities

Default stdio access follows the host process and file permissions. HTTP binds to `0.0.0.0` when a port is supplied. v1.1 does not implement authentication, authorization, rate limiting, persistent audit storage, electronic analyst signoff, or a model loop. A host must provide access and network controls before any shared sandbox use. These configurations have not been redeployed as part of this reconciliation.

Live API availability, data completeness and declaration-specific cost-share authority are outside this server's control. A brief re-checks the selected rule using its default thresholds. It does not inherit a prior screen's custom thresholds automatically, and its category baseline is described as text rather than a separate structured data-scope block.

For a security concern, use the repository's private security reporting feature if enabled, or contact the maintainers through an established private channel. Do not post secrets or sensitive records in public comments.
