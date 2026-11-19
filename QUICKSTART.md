# Run and verify the submission

Prerequisites: Git, uv, Python 3.12 and a terminal. Commands run from the repository root. uv can install a compatible Python if needed.

```sh
git clone https://github.com/gsa-mcp-hackathon/2026-HACKATHON.git
cd 2026-HACKATHON
uv sync --extra dev --frozen
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python eval/run_evaluation.py --output-dir eval/results/my-offline-run
```

Expected offline result: 63 tests and 33 evaluation checks. The evaluation uses the included dated public-data fixtures and makes no FEMA request. Generated latency depends on the machine. Use a new output directory so checked-in evidence remains unchanged.

## Connect an MCP client locally

Run `uv run python main.py` as a stdio subprocess from this directory. The server waits for MCP messages; that is normal. In clients that accept JSON configuration, use:

```json
{
  "mcpServers": {
    "fema-oversight": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/2026-HACKATHON", "run", "python", "main.py"]
    }
  }
}
```

Replace the directory with your actual absolute path. On Windows, use forward slashes or escaped backslashes. The exact configuration location depends on the client. Tool discovery should return [these six tools](docs/TOOLS.md), two resources and one prompt.

## Optional live verification

```sh
uv run python eval/run_evaluation.py --live --output-dir eval/results/my-live-run
```

This adds four live checks. It requires OpenFEMA availability and may fail or return changed counts as public data refreshes. An upstream timeout is a failed or incomplete live run, never an offline pass.

## Optional sandbox HTTP

PowerShell:

```powershell
$env:PORT='8080'
uv run python main.py
```

POSIX shell:

```sh
PORT=8080 uv run python main.py
```

Connect a streamable-HTTP MCP client to `http://localhost:8080/mcp`. There is no `/health` route in v1.1. HTTP binds to all interfaces and does not add authentication. Use controlled sandbox access; [deployment notes](deploy/README.md).
