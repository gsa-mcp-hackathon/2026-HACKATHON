# Repository cleanup on November 19 2026

The root `src/fema_oversight/` is now the only submitted server implementation: version 1.1.0. It was promoted unchanged from `SUBMISSION_FINAL/mcp_server_v1_1/src/`. The source fingerprint is identical to the original v1.1 report. The root entry point, dependencies and transport configs now point to it.

Removed from the current branch: the complete `HACKATHON_BACKUP_2026_11_03` tree, the redundant `SUBMISSION_FINAL` packaging tree after promoting its server, the superseded root v1.0 server and tests, old presentation and submission ZIPs, obsolete judge briefs and evaluation documents, earlier duplicate evaluation runs, the Windows-incompatible timestamped Python filename, unused IBM deployment recipes and stale hosted registry metadata.

Retained: the TTS MIT license, one canonical source and test suite, three runnable evaluation/demo/transport scripts, the minimal public-data control fixture, the clearly dated November 18 v1.1 report, current full machine-readable results, matching deck and Word package, PDF previews, and direct reviewer guides. The optional container and sandbox configs do not claim a new deployment.

The full prior tree remains in Git history at `1a3aa20f54a8d35a8f269fca50e1656182baef00`. No history rewrite, branch deletion or remote deployment was performed. A local Git bundle also preserves the pre-cleanup state.

The evaluation harness now defaults to the included fixture, normalizes source paths for a portable fingerprint, and preserves offline evidence if a live suite cannot complete. Numerical rules and submitted server source were not changed. Source SHA-256: `6dee75f765962a954ca75ca7cb5884d5f198f48eac87d3408fa7cff78386dd98`.
