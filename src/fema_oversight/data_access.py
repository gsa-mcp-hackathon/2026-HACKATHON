"""Record retrieval, separated from the review rules.

Tools describe *what* records they need with a ``PAQuery``. A ``RecordSource``
decides *how* to get them:

* ``OpenFEMASource``  live public API, hardened (fixed origin, timeout, size cap)
* ``SnapshotSource``  an archived list of records, used by tests and the
  evaluation harness so results can be reproduced exactly

Because both implement the same interface, the tool code that runs in
evaluation is the same code that runs in production.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol

import httpx

from fema_oversight.errors import ErrorCode, ReviewToolError

OPENFEMA_BASE_URL = "https://www.fema.gov/api/open/"
PA_ENTITY = "PublicAssistanceFundedProjectsDetails"
PA_PATH = f"v2/{PA_ENTITY}"
OPENFEMA_MAX_TOP = 10_000
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 20_000_000
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 0.25
DEFAULT_CACHE_TTL_SECONDS = 60.0
DEFAULT_CACHE_ENTRIES = 128


@dataclass(frozen=True)
class PAQuery:
    """A declarative request for PA Funded Projects Details records."""

    fields: tuple[str, ...]
    record_cap: int
    state_code: str | None = None
    disaster_number: int | None = None
    damage_category_code: str | None = None
    pw_number: int | None = None
    applicant_id: str | None = None
    min_total_obligated: float | None = None

    def to_odata_filter(self) -> str | None:
        """Render the query as an OData $filter. Inputs are pre-validated."""
        clauses: list[str] = []
        if self.state_code:
            clauses.append(f"stateAbbreviation eq '{_odata_literal(self.state_code)}'")
        if self.disaster_number:
            clauses.append(f"disasterNumber eq {int(self.disaster_number)}")
        if self.damage_category_code:
            clauses.append(f"damageCategoryCode eq '{_odata_literal(self.damage_category_code)}'")
        if self.pw_number:
            clauses.append(f"pwNumber eq {int(self.pw_number)}")
        if self.applicant_id:
            clauses.append(f"applicantId eq '{_odata_literal(self.applicant_id)}'")
        if self.min_total_obligated is not None:
            clauses.append(f"totalObligated ge {float(self.min_total_obligated)}")
        return " and ".join(clauses) or None

    def matches(self, record: dict[str, Any]) -> bool:
        """Apply the same filter in memory (used by ``SnapshotSource``)."""
        checks = [
            (self.state_code, record.get("stateAbbreviation")),
            (self.disaster_number, record.get("disasterNumber")),
            (self.damage_category_code, record.get("damageCategoryCode")),
            (self.pw_number, record.get("pwNumber")),
            (self.applicant_id, record.get("applicantId")),
        ]
        if any(wanted and value != wanted for wanted, value in checks):
            return False
        if self.min_total_obligated is not None:
            total = to_number(record.get("totalObligated"))
            if total is None or total < self.min_total_obligated:
                return False
        return True


@dataclass
class FetchResult:
    records: list[dict[str, Any]]
    record_cap: int
    retrieved_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def possibly_truncated(self) -> bool:
        return len(self.records) >= self.record_cap

    @property
    def source_last_refresh(self) -> str | None:
        stamps = [r["lastRefresh"] for r in self.records if isinstance(r.get("lastRefresh"), str)]
        return max(stamps) if stamps else None


class RecordSource(Protocol):
    async def fetch(self, query: PAQuery) -> FetchResult: ...


class OpenFEMASource:
    """Read-only client for the fixed OpenFEMA origin.

    Security posture: the origin is a constant, the path is a constant, redirects
    and environment proxies are disabled, responses are size-capped while
    streaming, and every upstream failure is converted to a sanitized
    ``ReviewToolError`` (no URLs, headers, or stack traces reach the agent).
    """

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._transport = transport  # injectable for tests
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._sleep = sleep

    async def fetch(self, query: PAQuery) -> FetchResult:
        """Fetch records, retrying only failures explicitly marked retryable."""
        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await self._fetch_once(query)
            except ReviewToolError as exc:
                if not exc.retryable or attempt == self._retry_attempts:
                    raise
                await self._sleep(self._retry_delay_seconds * (2 ** (attempt - 1)))
        raise AssertionError("retry loop exhausted without returning or raising")

    async def _fetch_once(self, query: PAQuery) -> FetchResult:
        """Execute one bounded OpenFEMA request and validate its envelope."""
        cap = min(max(query.record_cap, 1), OPENFEMA_MAX_TOP)
        params: dict[str, Any] = {"$top": cap, "$format": "json", "$select": ",".join(query.fields)}
        odata_filter = query.to_odata_filter()
        if odata_filter:
            params["$filter"] = odata_filter
        payload = await self._get_json(params)
        records = payload.get(PA_ENTITY) if isinstance(payload, dict) else None
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise ReviewToolError(
                ErrorCode.UPSTREAM_INVALID_RESPONSE,
                "OpenFEMA returned a response without a valid record list.",
                "Retry later; the dataset may be refreshing.",
                retryable=True,
            )
        return FetchResult(records=records, record_cap=cap)

    async def _get_json(self, params: dict[str, Any]) -> Any:
        try:
            async with (
                httpx.AsyncClient(
                    base_url=OPENFEMA_BASE_URL,
                    follow_redirects=False,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    trust_env=False,
                    transport=self._transport,
                ) as client,
                client.stream("GET", PA_PATH, params=params) as response,
            ):
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ReviewToolError(
                            ErrorCode.UPSTREAM_INVALID_RESPONSE,
                            "OpenFEMA response exceeded the 20 MB safety limit.",
                            "Narrow the request with disaster_number or a damage category.",
                        )
                return json.loads(body)
        except ReviewToolError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ReviewToolError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                f"OpenFEMA returned HTTP {status}.",
                "Retry in a few seconds." if status >= 500 or status == 429 else "Check the filters.",
                retryable=status >= 500 or status == 429,
            ) from None
        except httpx.TimeoutException:
            raise ReviewToolError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "OpenFEMA did not respond within 30 seconds.",
                "Retry, or narrow the request with disaster_number.",
                retryable=True,
            ) from None
        except httpx.RequestError:
            raise ReviewToolError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "Could not reach OpenFEMA.",
                "Retry later.",
                retryable=True,
            ) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ReviewToolError(
                ErrorCode.UPSTREAM_INVALID_RESPONSE,
                "OpenFEMA returned invalid JSON.",
                "Retry later.",
                retryable=True,
            ) from None


class SnapshotSource:
    """Serves an archived record list exactly as OpenFEMA would have."""

    def __init__(self, records: list[dict[str, Any]], retrieved_at: str | None = None) -> None:
        self._records = records
        self._retrieved_at = retrieved_at

    async def fetch(self, query: PAQuery) -> FetchResult:
        cap = min(max(query.record_cap, 1), OPENFEMA_MAX_TOP)
        rows = [r for r in self._records if query.matches(r)][:cap]
        result = FetchResult(records=rows, record_cap=cap)
        if self._retrieved_at:
            result.retrieved_at = self._retrieved_at
        return result


class CachingRecordSource:
    """Short-lived bounded cache with single-flight request coalescing.

    OpenFEMA refreshes daily, while agents often call several tools over the same
    scope in quick succession. This wrapper avoids duplicate network requests and
    keeps cache lifetime deliberately short. Failures are never cached.
    """

    def __init__(
        self,
        source: RecordSource,
        *,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        max_entries: int = DEFAULT_CACHE_ENTRIES,
    ) -> None:
        self._source = source
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._max_entries = max(1, max_entries)
        self._cache: OrderedDict[PAQuery, tuple[float, FetchResult]] = OrderedDict()
        self._inflight: dict[PAQuery, asyncio.Task[FetchResult]] = {}
        self._lock = asyncio.Lock()

    async def fetch(self, query: PAQuery) -> FetchResult:
        now = monotonic()
        async with self._lock:
            cached = self._cache.get(query)
            if cached and now - cached[0] <= self._ttl_seconds:
                self._cache.move_to_end(query)
                return cached[1]
            if cached:
                del self._cache[query]
            task = self._inflight.get(query)
            owner = task is None
            if owner:
                task = asyncio.create_task(self._source.fetch(query))
                self._inflight[query] = task
        assert task is not None
        try:
            result = await task
        finally:
            if owner:
                async with self._lock:
                    self._inflight.pop(query, None)
        if owner:
            async with self._lock:
                self._cache[query] = (monotonic(), result)
                self._cache.move_to_end(query)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
        return result


def to_number(value: Any) -> float | None:
    """OpenFEMA sometimes sends numbers as strings; return a finite float or None."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _odata_literal(value: str) -> str:
    """Escape a string for an OData single-quoted literal."""
    return value.replace("'", "''")
