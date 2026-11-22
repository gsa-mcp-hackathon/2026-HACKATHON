# Sandbox transport configuration

The submitted v1.1 server runs locally over stdio without a cloud account. Shared sandbox deployment is optional and is not required to reproduce the tests.

`server.main()` selects HTTP when `DATABRICKS_APP_PORT` or `PORT` is set, in that precedence order. Endpoint: `/mcp`. Otherwise it selects stdio. There is no browser analyst page or `/health` endpoint in this version.

| Configuration | Purpose | Verification scope |
| --- | --- | --- |
| `app.yaml` | Databricks App command with `PYTHONPATH=src` | Configuration only; no new deployment claimed |
| `Dockerfile` | Python 3.12 container, HTTP port 8080 | Recipe only; container build not run in this reconciliation |
| `manifest.yaml` | Optional Cloud Foundry process with port health check and no public route | Configuration only; not deployed |

For a controlled local HTTP session, follow [Quickstart](../QUICKSTART.md). A hosting platform must supply authentication, access restrictions and operational controls. The hackathon calls for sandbox prototypes. Do not treat the presence of deployment files as a production release or a live endpoint.
