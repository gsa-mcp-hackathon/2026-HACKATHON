# How the GSA template was adapted

Upstream reference: [GSA-TTS/mcp-hackathon-template](https://github.com/GSA-TTS/mcp-hackathon-template), commit [`f39249f1768309e3ef8b31742390a4f3a656b5f3`](https://github.com/GSA-TTS/mcp-hackathon-template/tree/f39249f1768309e3ef8b31742390a4f3a656b5f3), inspected November 19, 2026.

The FEMA repository is a domain adaptation of the template's Python/FastMCP pattern. Its GitHub fork relationship is to `phebeong/2026-HACKATHON`, not to the GSA template. This map explains the concrete implementation relationship; it does not claim an unverified Git ancestry or unchanged upstream files.

| Template component at the pinned revision | Submitted FEMA implementation | What changed |
| --- | --- | --- |
| [`main.py`](https://github.com/GSA-TTS/mcp-hackathon-template/blob/f39249f1768309e3ef8b31742390a4f3a656b5f3/main.py) | [`main.py`](../main.py) | Calls the FEMA package entry point |
| [`src/example_server/app.py`](https://github.com/GSA-TTS/mcp-hackathon-template/blob/f39249f1768309e3ef8b31742390a4f3a656b5f3/src/example_server/app.py) | [`server.py`](../src/fema_oversight/server.py) | Thin FastMCP assembly, tool registration, resources, prompt, stdio/port-selected HTTP |
| `src/example_server/tools/` | [`screening.py`](../src/fema_oversight/tools/screening.py), [`review.py`](../src/fema_oversight/tools/review.py) | Replaced examples with six goal-based FEMA actions |
| `models.py` | [`schemas/inputs.py`](../src/fema_oversight/schemas/inputs.py), [`schemas/outputs.py`](../src/fema_oversight/schemas/outputs.py) | Per-tool validated requests and typed results |
| `utils.py`, `config.py` | [`data_access.py`](../src/fema_oversight/data_access.py), [`errors.py`](../src/fema_oversight/errors.py) | Fixed public API, bounded retrieval, injectable snapshots, sanitized errors; unused settings dependency removed |
| `prompts/`, `resources/` | [`server.py`](../src/fema_oversight/server.py), [`methodology.py`](../src/fema_oversight/methodology.py) | Two resources and one workflow prompt registered directly; methodology shared with tools |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | [Package](../pyproject.toml), [lock](../uv.lock), [runtime constraints](../requirements.txt) | Renamed package, v1.1.0, pinned tested dependencies |
| `tests/`, `eval/` | [63-test suite](../tests/), [independent evaluation](../eval/) | Added fixture controls, invalid-input and upstream cases, contract and stability checks |
| `deploy/`, `Dockerfile`, `manifest.yaml` | [Sandbox notes](../deploy/README.md), [container recipe](../Dockerfile), [manifest](../manifest.yaml) | Retained optional transport packaging; removed unused IBM recipes and fixed public routes |
| `README.md`, `QUICKSTART.md`, `SECURITY.md`, `LICENSE` | [Entry](../README.md), [run instructions](../QUICKSTART.md), [security](../SECURITY.md), [license](../LICENSE) | FEMA-specific reviewer path; original TTS MIT notice retained |

Deliberate departures: the template's example health route is not implemented, so configurations use a port check. Prompts and resources are registered in `server.py` rather than separate aggregator packages. Rules are separated into [`indicators.py`](../src/fema_oversight/indicators.py) for testing without MCP or HTTP. The template's optional evaluation approach was replaced with the checked-in SQLite/MCP harness; no Phoenix evaluation is claimed.

## Trace it yourself

1. Open `main.py`, then `server.build_server()`.
2. Follow the calls to `screening.register()` and `review.register()`.
3. Open the Pydantic model named in a tool signature.
4. Follow its rule into `indicators.py` and retrieval into `data_access.py`.
5. Run the [quickstart checks](../QUICKSTART.md) and compare the [recorded evidence](../eval/README.md).

This supplies the repository, technical approach and testing path requested on the [official GSA event page](https://www.gsa.gov/super-intelligence/si-community-of-practice/events-and-training/mcp-server-and-si-agent-government-hackathon).
