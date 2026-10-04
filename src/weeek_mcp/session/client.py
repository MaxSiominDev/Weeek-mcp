"""The web app's own API, authenticated with the browser session cookie.

Weeek restricted API tokens to project owners and rejects bearer tokens here
outright, so the cookie is the only way in. Undocumented.
"""

from __future__ import annotations

import httpx2

from ..errors import ApiError, SessionExpired, TaskNotFound
from ..http import UNAUTHENTICATED, envelope, failure_code, raise_for_envelope, request
from .cookies import is_session_cookie, to_header

BASE = "https://api.weeek.net"

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.weeek.net/",
    "Origin": "https://app.weeek.net",
}


class SessionApi:
    def __init__(self, cookies: dict[str, str], client: httpx2.AsyncClient) -> None:
        self._jar = dict(cookies)
        self._client = client
        # Set when Weeek reissues the session mid-request; the caller persists it.
        self.refreshed = False

    @property
    def cookies(self) -> dict[str, str]:
        return dict(self._jar)

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {**_HEADERS, "Cookie": to_header(self._jar)}

    def _absorb(self, response: httpx2.Response) -> None:
        for name, value in response.cookies.items():
            if is_session_cookie(name) and self._jar.get(name) != value:
                self._jar[name] = value
                self.refreshed = True

    async def workspaces(self) -> list[dict]:
        return (await self._get("/ws")).get("workspaces", [])

    async def task_with_comments(self, workspace_id: int, task_id: int) -> dict:
        try:
            body = await self._get(
                f"/ws/{workspace_id}/tm/tasks/{task_id}", params={"withSubtasks": 1}
            )
        except ApiError as exc:
            if exc.status == 404:
                raise TaskNotFound(task_id) from None
            raise
        task = body.get("task")
        if not task:
            raise TaskNotFound(task_id)
        return task

    async def task_files(self, workspace_id: int, task_id: int) -> list[dict]:
        # The task payload only carries filesCount.
        return (await self._get(f"/ws/{workspace_id}/tm/tasks/{task_id}/files")).get("files", [])

    async def members(self, workspace_id: int) -> list[dict]:
        return (await self._get(f"/ws/{workspace_id}/members")).get("data", [])

    async def projects(self, workspace_id: int) -> list[dict]:
        return (await self._get(f"/ws/{workspace_id}/tm/projects")).get("projects", [])

    async def download(self, url: str) -> httpx2.Response:
        response = await request(
            self._client,
            "GET",
            url,
            headers={
                "Cookie": to_header(self._jar),
                "Referer": _HEADERS["Referer"],
                "Accept": "*/*",
            },
        )
        self._absorb(response)
        return response

    async def _get(self, path: str, params: dict | None = None) -> dict:
        response = await request(
            self._client, "GET", f"{BASE}{path}", headers=self._auth_headers, params=params
        )
        self._absorb(response)
        if response.status_code in (401, 403):
            raise SessionExpired()

        body = envelope(response)
        # An expired session answers HTTP 200 with a failure envelope.
        if failure_code(body) == UNAUTHENTICATED:
            raise SessionExpired()

        if response.status_code >= 400 and body.get("success") is not False:
            raise ApiError(response.status_code, None, str(body.get("message", "request failed")))

        raise_for_envelope(response, body)
        return body
