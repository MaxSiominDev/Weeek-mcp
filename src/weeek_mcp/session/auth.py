"""Sign in against the web app's JSON endpoint. Undocumented, and rate
limited to 5 attempts per window."""

from __future__ import annotations

import httpx2

from ..errors import WeeekError
from ..http import envelope, request
from .cookies import REQUIRED, select_session_cookies

LOGIN_URL = "https://api.weeek.net/auth/login"

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://app.weeek.net",
    "Referer": "https://app.weeek.net/",
}


class LoginFailed(WeeekError):
    pass


async def login(email: str, password: str, client: httpx2.AsyncClient) -> dict[str, str]:
    # remember=true also issues the remember-me cookie.
    response = await request(
        client,
        "POST",
        LOGIN_URL,
        headers=_HEADERS,
        json={"email": email, "password": password, "remember": True},
    )

    body = _body(response)
    if response.status_code == 429:
        raise LoginFailed(
            "Weeek is rate limiting sign-in (5 attempts per window). Wait a few "
            "minutes before trying again."
        )
    if response.status_code >= 400 or body.get("success") is False:
        raise LoginFailed(_reason(body))

    jar = _harvest(response)
    if REQUIRED not in jar:
        raise LoginFailed(
            "Weeek accepted the credentials but issued no session cookie. The "
            "account may require two-factor authentication or SSO, which this "
            "sign-in cannot complete. Use `weeek-mcp login --cookie` instead."
        )
    return jar


def _body(response: httpx2.Response) -> dict:
    try:
        return envelope(response)
    except WeeekError:
        # A captcha challenge answers in HTML.
        return {}


def _reason(body: dict) -> str:
    message = str(body.get("message") or "").strip()
    errors = body.get("errors")
    if isinstance(errors, dict):
        for messages in errors.values():
            if isinstance(messages, list) and messages:
                message = message or str(messages[0])
                break
    return message or "Weeek rejected the sign-in and gave no reason."


def _harvest(response: httpx2.Response) -> dict[str, str]:
    return select_session_cookies(response.cookies.items())
