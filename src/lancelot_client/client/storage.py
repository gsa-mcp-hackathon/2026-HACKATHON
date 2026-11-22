"""Writes to the shared trace volume (brief section 5).

The client writes ONLY under client-runs/. runs/ and latest/ belong to the
server. Every write error is captured and returned; nothing here raises into
the test logic, so a storage failure can never hide or change a test result.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
from datetime import datetime, timezone

from client import config

VOLUME_ROOT = config.VOLUME_ROOT
CLIENT_ROOT = VOLUME_ROOT + "/client-runs"
LATEST_DIR = CLIENT_ROOT + "/latest"
SERVER_RUN_ID_RE = re.compile(r"^[a-z]+-(\d{4})(\d{2})(\d{2})T\d{6}Z-[0-9a-f]{6}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_client_run_id(now: datetime | None = None, rand_hex: str | None = None) -> str:
    now = now or utc_now()
    rand_hex = rand_hex or secrets.token_hex(3)
    return f"client-{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{rand_hex}"


def run_dir(client_run_id: str) -> str:
    m = re.match(r"^client-(\d{4})(\d{2})(\d{2})T\d{6}Z-[0-9a-f]{6}$", client_run_id)
    if not m:
        raise ValueError(f"not a clientRunId: {client_run_id!r}")
    return f"{CLIENT_ROOT}/{m.group(1)}-{m.group(2)}-{m.group(3)}/{client_run_id}"


def server_trace_path(server_run_id: str) -> str | None:
    """runs/<YYYY-MM-DD>/<runId>/trace.json for a server runId, else None."""
    m = SERVER_RUN_ID_RE.match(server_run_id or "")
    if not m:
        return None
    return f"{VOLUME_ROOT}/runs/{m.group(1)}-{m.group(2)}-{m.group(3)}/{server_run_id}/trace.json"


def assert_client_path(path: str) -> str:
    """Refuse any write outside client-runs/ (runs/ and latest/ are the server's)."""
    norm = os.path.normpath(path)
    if norm != path or not norm.startswith(CLIENT_ROOT + "/"):
        raise ValueError(f"refusing to write outside {CLIENT_ROOT}/: {path!r}")
    return norm


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "file"


class Storage:
    """Thin wrapper over databricks-sdk Files API, as the app service principal."""

    def __init__(self, workspace_client=None):
        self._w = workspace_client
        self.errors: list[dict] = []
        self.written: list[str] = []

    @property
    def w(self):
        if self._w is None:
            from databricks.sdk import WorkspaceClient

            self._w = WorkspaceClient()
        return self._w

    def write_bytes(self, path: str, data: bytes) -> bool:
        try:
            path = assert_client_path(path)
            self.w.files.upload(path, io.BytesIO(data), overwrite=True)
            self.written.append(path)
            return True
        except Exception as e:  # noqa: BLE001 - recorded, shown in UI
            self.errors.append({"path": path, "error": f"{type(e).__name__}: {e}"[:500]})
            return False

    def write_json(self, path: str, obj) -> bool:
        return self.write_bytes(path, json.dumps(obj, indent=2, sort_keys=False, default=str).encode("utf-8"))

    def read_json(self, path: str) -> tuple[dict | None, str | None]:
        """(obj, error). error is 'NOT_FOUND' when the file does not exist."""
        from databricks.sdk.errors import NotFound

        try:
            resp = self.w.files.download(path)
            raw = resp.contents.read()
            return json.loads(raw), None
        except NotFound:  # code review L5: the SDK's typed 404, not a guess from message text
            return None, "NOT_FOUND"
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"[:500]
