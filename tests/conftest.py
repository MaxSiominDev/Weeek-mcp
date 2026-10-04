from __future__ import annotations

import json
from collections.abc import Callable

import httpx2
import pytest


def client_returning(handler: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def json_response(payload: dict, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def html_response(status: int = 404) -> httpx2.Response:
    """What Weeek actually serves on an unknown path: a Laravel error page."""
    return httpx2.Response(
        status,
        content=b"<!DOCTYPE html><html><body>Not Found</body></html>",
        headers={"content-type": "text/html; charset=UTF-8"},
    )


UNAUTHENTICATED_BODY = {"success": False, "code": 2000000, "message": "Unauthenticated."}


@pytest.fixture
def recorded() -> list[httpx2.Request]:
    return []


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch):
    """Retries are real seconds. Tests care that a retry happened, not that it waited."""
    from weeek_mcp import http

    async def instant(_seconds):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", instant)
