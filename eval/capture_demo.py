"""Record an actual three-action MCP demonstration against live public OpenFEMA."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fastmcp import Client

from fema_oversight.server import build_server

CALLS = [
    ("build_review_queue", {"state_code": "LA", "disaster_number": 4611, "limit": 5}),
    (
        "screen_category_cost_outliers",
        {"state_code": "LA", "disaster_number": 4611, "damage_category_code": "F"},
    ),
    (
        "prepare_evidence_brief",
        {
            "pw_number": 1725,
            "disaster_number": 4611,
            "applicant_id": "109-99109-00",
            "indicator": "category_outlier",
        },
    ),
]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture = {"started_at": datetime.now(UTC).isoformat(), "mode": "live MCP, no model", "calls": []}
    async with Client(build_server()) as client:
        for name, params in CALLS:
            result = await client.call_tool(name, {"params": params}, raise_on_error=False)
            capture["calls"].append(
                {
                    "tool": name,
                    "arguments": {"params": params},
                    "is_error": result.is_error,
                    "structured_content": result.structured_content,
                    "error_text": [item.text for item in result.content if hasattr(item, "text")]
                    if result.is_error
                    else [],
                }
            )
    capture["completed_at"] = datetime.now(UTC).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(capture, indent=2), encoding="utf-8")
    passed = sum(not item["is_error"] for item in capture["calls"])
    print(f"{passed}/3 demonstration calls succeeded -> {args.output}")
    return 0 if passed == 3 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
