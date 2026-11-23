"""Stable one-command entry point for the reproducible offline evaluation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Run the production evaluation harness and replace ``results/latest``."""
    command = [
        sys.executable,
        str(ROOT / "eval" / "run_evaluation.py"),
        "--output-dir",
        str(ROOT / "evaluation" / "results" / "latest"),
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
