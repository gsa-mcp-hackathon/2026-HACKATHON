"""Deployment settings (code review L3).

Defaults match the current deployment. Override any of them with environment
variables in app.yaml; nothing else in the code hard-codes these values.
Invalid values fail at import time, so a bad setting cannot run silently.
"""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    v = (os.environ.get(name) or "").strip()
    return v or default


# Server under test.
SERVER_BASE = _env("LANCELOT_SERVER_BASE",
                   "https://mcp-lancelot-beta-7474654188777746.aws.databricksapps.com").rstrip("/")
# Shared trace volume. The client writes only under <VOLUME_ROOT>/client-runs/.
VOLUME_ROOT = _env("LANCELOT_VOLUME_ROOT", "/Volumes/users/tom_jacobson/lancelot_traces").rstrip("/")
# The user whose workspace folder holds the pre-provisioned V11 sample (DECISIONS.md D4, D5).
OWNER_EMAIL = _env("LANCELOT_OWNER_EMAIL", "tom.jacobson@hq.dhs.gov").lower()
# V11 in Mode A for OWNER_EMAIL: workspace path of sample.pdf in the owner's own folder.
OWNER_V11_PATH = _env("LANCELOT_OWNER_V11_PATH", f"/Users/{OWNER_EMAIL}/lancelot-client/samples/sample.pdf")
# V12 in Mode A for OWNER_EMAIL: a path in a folder that is not the caller's.
V12_OTHER_USER_PATH = _env("LANCELOT_V12_OTHER_USER_PATH",
                           "/Users/lancelot-v12-other-user@example.invalid/sample.pdf")


def validate() -> None:
    if not SERVER_BASE.startswith("https://"):
        raise ValueError(f"LANCELOT_SERVER_BASE must be an https:// URL, got {SERVER_BASE!r}")
    if not VOLUME_ROOT.startswith("/Volumes/") or ".." in VOLUME_ROOT.split("/"):
        raise ValueError(f"LANCELOT_VOLUME_ROOT must be a /Volumes/... path, got {VOLUME_ROOT!r}")
    if "@" not in OWNER_EMAIL:
        raise ValueError(f"LANCELOT_OWNER_EMAIL must be an email address, got {OWNER_EMAIL!r}")
    for name, p in (("LANCELOT_OWNER_V11_PATH", OWNER_V11_PATH), ("LANCELOT_V12_OTHER_USER_PATH", V12_OTHER_USER_PATH)):
        if not p.startswith("/Users/"):
            raise ValueError(f"{name} must start with /Users/, got {p!r}")
    if not OWNER_V11_PATH.startswith(f"/Users/{OWNER_EMAIL}/"):
        raise ValueError("LANCELOT_OWNER_V11_PATH must be inside the folder of LANCELOT_OWNER_EMAIL")


validate()
