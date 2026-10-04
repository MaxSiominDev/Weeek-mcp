"""Envelope and retry handling for the Weeek API."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx2

from .errors import ApiError, UnexpectedResponse

# An expired session answers HTTP 200 with this code, not with a 401.
UNAUTHENTICATED = 2000000

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3


async def request(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx2.Response:
    last: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx2.TransportError as exc:
            last = exc
        else:
            if response.status_code not in _RETRY_STATUSES:
                return response
            last = None

        if attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(2**attempt * (0.5 + random.random()))

    if last is not None:
        raise last
    return response


def envelope(response: httpx2.Response) -> dict:
    content_type = response.headers.get("content-type", "")
    # Unknown paths answer with a Laravel HTML page, not JSON.
    if "json" not in content_type.lower():
        raise UnexpectedResponse(response.status_code, content_type, str(response.url))

    try:
        body = response.json()
    except ValueError:
        raise UnexpectedResponse(response.status_code, content_type, str(response.url)) from None

    if not isinstance(body, dict):
        raise UnexpectedResponse(response.status_code, content_type, str(response.url))
    return body


def failure_code(body: dict) -> int | None:
    if body.get("success") is False:
        code = body.get("code")
        return code if isinstance(code, int) else -1
    return None


def raise_for_envelope(response: httpx2.Response, body: dict) -> None:
    code = failure_code(body)
    if code is not None:
        raise ApiError(response.status_code, code, str(body.get("message", "")))
