"""Verify actual stdio and local HTTP startup without requesting FEMA data."""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

ROOT = Path(__file__).resolve().parents[1]


async def inspect_client(transport) -> dict:
    async with Client(transport) as client:
        tools = sorted(tool.name for tool in await client.list_tools())
        resources = sorted(str(item.uri) for item in await client.list_resources())
        prompts = sorted(item.name for item in await client.list_prompts())
        result = await client.call_tool("explain_review_indicator", {"params": {"indicator": "category_outlier"}})
        assert len(tools) == 6 and len(resources) == 2 and len(prompts) == 1
        assert not result.is_error and result.structured_content["indicator"] == "category_outlier"
        return {"tools": tools, "resources": resources, "prompts": prompts, "explanation_passed": True}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryFile(mode="w+") as log:
        stdio = await inspect_client(
            PythonStdioTransport(
                ROOT / "main.py",
                python_cmd=sys.executable,
                cwd=str(ROOT),
                env={"PORT": "", "DATABRICKS_APP_PORT": ""},
                log_file=log,
            )
        )
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        env = {**os.environ, "PORT": str(port), "DATABRICKS_APP_PORT": ""}
        process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        try:
            for _ in range(100):
                with socket.socket() as probe:
                    probe.settimeout(0.1)
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        break
                if process.poll() is not None:
                    raise RuntimeError("HTTP subprocess exited before startup")
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Local HTTP listener did not start within ten seconds")
            http = await inspect_client(f"http://127.0.0.1:{port}/mcp")
        finally:
            process.terminate()
            process.wait(timeout=10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"verified_at": datetime.now(UTC).isoformat(), "stdio": stdio, "http": http}, indent=2),
        encoding="utf-8",
    )
    print("stdio and HTTP startup, discovery and explanation: PASS")


if __name__ == "__main__":
    asyncio.run(main())
