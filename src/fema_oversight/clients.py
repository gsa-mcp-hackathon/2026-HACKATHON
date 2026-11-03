"""External-service clients for the FEMA oversight server.

Tools should express *review actions*; they should not also own URL building,
metadata lookups, response caching, pagination semantics and upstream error
translation. This module centralizes those concerns for the OpenFEMA public API.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from fema_oversight.config import settings

MAX_RESPONSE_BYTES = 20_000_000
API_BASE_URL = "https://www.fema.gov/api/open/"
PA_ENTITY = "PublicAssistanceFundedProjectsDetails"
PA_PATH = f"v2/{PA_ENTITY}"
DATASETS_PATH = "v1/DataSets"

DATASET_PROVENANCE: dict[str, str] = {
    "source": "FEMA OpenFEMA Public Assistance Funded Projects Details (v2)",
    "publisher": "FEMA / U.S. Department of Homeland Security",
    "source_system": "Grants Manager (FAC-Trax)",
    "source_url": (
        "https://www.fema.gov/openfema-data-page/"
        "public-assistance-funded-projects-details-v2"
    ),
    "access": "public, no API key, read-only",
    "update_frequency": "daily (R/P1D)",
    "financial_caveat": (
        "Figures are from FEMA's Grants Manager, not FEMA's official financial "
        "system. Not for official reporting."
    ),
}


class UpstreamServiceError(RuntimeError):
    """Sanitized external-service failure safe to return to an MCP client."""


@dataclass(slots=True)
class PAFetchResult:
    """Records plus retrieval metadata needed for provenance and completeness."""

    records: list[dict[str, Any]]
    total_matches: int | None
    retrieved_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenFEMAClient:
    """Minimal, safe, cached client for the fixed OpenFEMA origin."""

    def __init__(self) -> None:
        self._response_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._dataset_refresh_cache: tuple[float, str] | None = None
        # Caps parallel requests to a free public API so one runaway agent
        # cannot degrade OpenFEMA for other users.
        self._semaphore = asyncio.Semaphore(settings.upstream_max_concurrency)

    @staticmethod
    def validate_relative_path(path: str) -> str:
        """Reject paths that could select or escape the configured API origin."""
        parsed = urlsplit(path)
        decoded_path = parsed.path
        for _ in range(3):
            decoded = unquote(decoded_path)
            if decoded == decoded_path:
                break
            decoded_path = decoded
        segments = decoded_path.replace("\\", "/").split("/")
        if (
            not path
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or decoded_path.startswith(("/", "\\"))
            or any(segment in {".", ".."} for segment in segments)
        ):
            raise ValueError(
                "path must be a relative API path without a query or fragment"
            )
        return path

    def _cache_key(self, path: str, params: dict[str, Any] | None) -> str:
        return json.dumps(
            [path, sorted((params or {}).items())],
            sort_keys=True,
            default=str,
        )

    def _read_response_cache(self, key: str) -> Any | None:
        if settings.response_cache_ttl_seconds <= 0:
            return None
        entry = self._response_cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            self._response_cache.pop(key, None)
            return None
        self._response_cache.move_to_end(key)
        return value

    def _write_response_cache(self, key: str, value: Any) -> None:
        if (
            settings.response_cache_ttl_seconds <= 0
            or settings.response_cache_max_entries <= 0
        ):
            return
        self._response_cache[key] = (
            time.time() + settings.response_cache_ttl_seconds,
            value,
        )
        self._response_cache.move_to_end(key)
        while len(self._response_cache) > settings.response_cache_max_entries:
            self._response_cache.popitem(last=False)

    async def fetch_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """GET a path from the fixed OpenFEMA origin and return parsed JSON."""
        safe_path = self.validate_relative_path(path)
        cache_key = self._cache_key(safe_path, params)
        cached = self._read_response_cache(cache_key)
        if cached is not None:
            return cached
        try:
            async with self._semaphore:
                async with httpx.AsyncClient(
                    base_url=API_BASE_URL,
                    follow_redirects=False,
                    timeout=timeout or settings.upstream_timeout_seconds,
                    trust_env=False,
                ) as client:
                    # GET only: this client has no code path that can write.
                    async with client.stream(
                        "GET", safe_path, params=params
                    ) as response:
                        response.raise_for_status()
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_RESPONSE_BYTES:
                                raise UpstreamServiceError(
                                    "Upstream response exceeded the size limit."
                                )
                        payload = json.loads(content)
                        self._write_response_cache(cache_key, payload)
                        return payload
        except UpstreamServiceError:
            raise
        except httpx.HTTPStatusError as exc:
            message = f"Upstream service returned status {exc.response.status_code}."
            if exc.response.status_code == 429:
                message = (
                    "OpenFEMA rate limited the request. Narrow the query and "
                    "retry later."
                )
            raise UpstreamServiceError(message) from None
        except (httpx.DecodingError, json.JSONDecodeError, UnicodeDecodeError):
            raise UpstreamServiceError(
                "Upstream service returned invalid JSON."
            ) from None
        except httpx.RequestError:
            raise UpstreamServiceError("Upstream service request failed.") from None

    async def fetch_pa_records(
        self,
        *,
        odata_filter: str | None = None,
        select: list[str] | None = None,
        top: int = 1000,
        orderby: str | None = None,
        include_count: bool = False,
    ) -> PAFetchResult:
        """Fetch PA records and return rows plus completeness metadata."""
        params: dict[str, Any] = {"$top": min(max(top, 1), 10000), "$format": "json"}
        if odata_filter:
            params["$filter"] = odata_filter
        if select:
            params["$select"] = ",".join(select)
        if orderby:
            params["$orderby"] = orderby
        if include_count:
            params["$count"] = "true"
        payload = await self.fetch_json(PA_PATH, params=params)
        if not isinstance(payload, dict) or PA_ENTITY not in payload:
            raise UpstreamServiceError("Upstream response omitted the dataset records.")
        records = payload[PA_ENTITY]
        if not isinstance(records, list) or any(
            not isinstance(r, dict) for r in records
        ):
            raise UpstreamServiceError(
                "Upstream response has an invalid record structure."
            )
        metadata = payload.get("metadata", {})
        count_value = metadata.get("count") if isinstance(metadata, dict) else None
        total_matches = (
            int(count_value)
            if isinstance(count_value, (int, str)) and str(count_value).isdigit()
            else None
        )
        retrieved_at = metadata.get("rundate") if isinstance(metadata, dict) else None
        return PAFetchResult(
            records=records,
            total_matches=total_matches,
            retrieved_at=retrieved_at or _utc_now(),
        )

    async def get_dataset_last_updated(self) -> str:
        """Return OpenFEMA's published last refresh timestamp for this dataset."""
        if not settings.provenance_lookup_enabled:
            return "Source update timestamp lookup disabled"
        cached = self._dataset_refresh_cache
        if cached and time.time() < cached[0]:
            return cached[1]
        payload = await self.fetch_json(
            DATASETS_PATH,
            params={
                "$filter": "name eq 'PublicAssistanceFundedProjectsDetails'",
                "$select": "name,lastDataSetRefresh,lastRefresh",
                "$format": "json",
            },
        )
        last_updated = "Source update timestamp not retrieved"
        if isinstance(payload, dict):
            rows = payload.get("DataSets")
            if isinstance(rows, list) and rows:
                row = rows[0]
                if isinstance(row, dict):
                    last_updated = (
                        row.get("lastDataSetRefresh")
                        or row.get("lastRefresh")
                        or last_updated
                    )
        self._dataset_refresh_cache = (
            time.time() + settings.provenance_cache_ttl_seconds,
            last_updated,
        )
        return last_updated


openfema_client = OpenFEMAClient()
