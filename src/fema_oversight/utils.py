"""Shared orchestration helpers used by the tool layer.

This module intentionally contains *no* tool registration. It exposes:
* thin compatibility wrappers (`fetch_json`, `fetch_pa_records`) that preserve
  the existing monkeypatch seam used by tests and eval scripts;
* provenance assembly;
* pagination helpers;
* low-level numeric coercion and OData escaping.
"""

from __future__ import annotations

import json
import math
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from fema_oversight.clients import (
    API_BASE_URL,
    DATASET_PROVENANCE,
    MAX_RESPONSE_BYTES,
    PA_ENTITY,
    PA_PATH,
    PAFetchResult,
    UpstreamServiceError,
    openfema_client,
)
from fema_oversight.methodology import REVIEW_CAVEAT
from fema_oversight.models import (
    MAX_PAGE_SIZE,
    DataScope,
    PaginationParams,
    ProvenanceBlock,
)

DEFAULT_TIMEOUT = 30.0


def _validate_relative_path(path: str) -> str:
    """Compatibility wrapper around the historical path validator for tests."""
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
        raise ValueError("path must be a relative API path without a query or fragment")
    return path


async def fetch_json(
    path: str,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Compatibility wrapper used by existing security tests.

    Intentionally keeps its own small implementation so tests can monkeypatch
    ``utils.httpx.AsyncClient`` and verify the fixed-origin client policy.
    """
    safe_path = _validate_relative_path(path)
    try:
        async with httpx.AsyncClient(
            base_url=API_BASE_URL,
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
        ) as client:
            async with client.stream("GET", safe_path, params=params) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise UpstreamServiceError(
                            "Upstream response exceeded the size limit."
                        )
                return json.loads(content)
    except UpstreamServiceError:
        raise
    except httpx.HTTPStatusError as exc:
        raise UpstreamServiceError(
            f"Upstream service returned status {exc.response.status_code}."
        ) from None
    except (httpx.DecodingError, json.JSONDecodeError, UnicodeDecodeError):
        raise UpstreamServiceError("Upstream service returned invalid JSON.") from None
    except httpx.RequestError:
        raise UpstreamServiceError("Upstream service request failed.") from None


async def fetch_pa_records(
    odata_filter: str | None = None,
    select: list[str] | None = None,
    top: int = 1000,
    orderby: str | None = None,
) -> list[dict[str, Any]]:
    """Compatibility wrapper returning only records.

    Some existing tests and evaluation scripts monkeypatch this function to
    return a plain list, so the tools keep importing it from this module. New
    code that also needs metadata should call ``fetch_pa_records_with_meta``.
    """
    params: dict[str, Any] = {"$top": min(max(top, 1), 10000), "$format": "json"}
    if odata_filter:
        params["$filter"] = odata_filter
    if select:
        params["$select"] = ",".join(select)
    if orderby:
        params["$orderby"] = orderby
    payload = await fetch_json(PA_PATH, params=params)
    if not isinstance(payload, dict) or PA_ENTITY not in payload:
        raise UpstreamServiceError("Upstream response omitted the dataset records.")
    records = payload[PA_ENTITY]
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise UpstreamServiceError("Upstream response has an invalid record structure.")
    return records


async def fetch_pa_records_with_meta(
    odata_filter: str | None = None,
    select: list[str] | None = None,
    top: int = 1000,
    orderby: str | None = None,
    include_count: bool = False,
) -> PAFetchResult:
    """Fetch PA records plus completeness metadata for provenance blocks."""
    return await openfema_client.fetch_pa_records(
        odata_filter=odata_filter,
        select=select,
        top=top,
        orderby=orderby,
        include_count=include_count,
    )


def to_float(value: Any) -> float | None:
    """Best-effort numeric coercion; OpenFEMA delivers many numbers as strings."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


async def provenance_block(
    methodology: str, as_of: str | None = None
) -> dict[str, str]:
    """Return the provenance stamp carried on every tool output.

    Deprecated for tool implementations because it issues its own metadata calls.
    Use ``provenance_block_from_result`` whenever you already have an upstream
    fetch timestamp and want provenance without extra latency.
    """
    return ProvenanceBlock(
        source=DATASET_PROVENANCE["source"],
        last_updated=as_of or await openfema_client.get_dataset_last_updated(),
        update_frequency=DATASET_PROVENANCE["update_frequency"],
        retrieved_at=(await openfema_client.fetch_pa_records(top=1)).retrieved_at,
        methodology=methodology,
        limitations=(
            DATASET_PROVENANCE["financial_caveat"]
            + " Detection tools analyze at most 5,000 cost-share records or "
            "10,000 repeated-worksheet/category records per call. Results and "
            "baselines describe the retrieved subset, not the full dataset. "
            "Cost-share bands do not verify declaration-specific authorizations; "
            "authorized 100% shares may be returned."
        ),
        review_status=REVIEW_CAVEAT,
    ).model_dump()


def provenance_block_from_result(
    methodology: str,
    *,
    retrieval_timestamp: str | None,
    source_last_updated: str,
    limitations_suffix: str = "",
) -> dict[str, str]:
    """Build provenance using an already executed upstream fetch.

    Tools should prefer this helper so they do not make a second network call
    just to stamp ``retrieved_at``.
    """
    return ProvenanceBlock(
        source=DATASET_PROVENANCE["source"],
        last_updated=source_last_updated,
        update_frequency=DATASET_PROVENANCE["update_frequency"],
        retrieved_at=retrieval_timestamp or "Source retrieval timestamp not returned",
        methodology=methodology,
        limitations=DATASET_PROVENANCE["financial_caveat"] + limitations_suffix,
        review_status=REVIEW_CAVEAT,
    ).model_dump()


def build_data_scope(
    *,
    records_retrieved: int,
    record_cap: int,
    upstream_total_matches: int | None = None,
    disaster_filter: int | None = None,
    baseline: str | None = None,
) -> dict[str, Any]:
    """Create a standard completeness / truncation statement."""
    possibly_truncated = records_retrieved >= record_cap or (
        upstream_total_matches is not None
        and upstream_total_matches > records_retrieved
    )
    return DataScope(
        records_retrieved=records_retrieved,
        record_cap=record_cap,
        possibly_truncated=possibly_truncated,
        upstream_total_matches=upstream_total_matches,
        disaster_filter=disaster_filter,
        baseline=baseline,
    ).model_dump(exclude_none=True)


def odata_quote(value: str) -> str:
    """Single-quote-escape a string for an OData filter literal."""
    return value.replace("'", "''")


def paginate(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    """Slice a list and return a standard pagination envelope."""
    total = len(items)
    window = items[offset : offset + limit]
    next_offset = offset + len(window)
    return {
        "total": total,
        "count": len(window),
        "offset": offset,
        "items": window,
        "has_more": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
    }


def resolve_pagination(pagination: PaginationParams | None) -> PaginationParams:
    """Normalize optional pagination to the shared default object."""
    return pagination or PaginationParams(limit=min(25, MAX_PAGE_SIZE), offset=0)
