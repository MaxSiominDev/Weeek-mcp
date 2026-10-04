import json

import httpx2
import pytest

from conftest import client_returning
from weeek_mcp.session.auth import LoginFailed, login

SESSION = "weeek_session=fresh; expires=Thu, 06 Aug 2026 02:26:41 GMT; Max-Age=7200; path=/; secure; httponly"
REMEMBER = "remember_app_59ba=r3member; path=/; secure; httponly"
NOISE = "_ym_uid=1712; path=/"


def responding(status: int, body: dict, cookies: list[str] = ()) -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        handler.seen = request  # type: ignore[attr-defined]
        headers = [("content-type", "application/json")]
        headers += [("set-cookie", c) for c in cookies]
        return httpx2.Response(status, content=json.dumps(body).encode(), headers=headers)

    client = client_returning(handler)
    client.handler = handler  # type: ignore[attr-defined]
    return client


async def test_a_successful_sign_in_returns_the_session_cookies():
    async with responding(
        200, {"success": True}, [SESSION, REMEMBER, NOISE]
    ) as client:
        jar = await login("max@example.com", "s3cret", client)

    assert jar["weeek_session"] == "fresh"
    assert jar["remember_app_59ba"] == "r3member"
    # Analytics cookies from the login response have no business being stored.
    assert "_ym_uid" not in jar


async def test_remember_me_is_requested_so_a_lapsed_session_can_be_reissued():
    client = responding(200, {"success": True}, [SESSION])
    async with client:
        await login("max@example.com", "s3cret", client)

    sent = json.loads(client.handler.seen.content)
    assert sent == {"email": "max@example.com", "password": "s3cret", "remember": True}


async def test_wrong_credentials_report_what_weeek_said():
    """Verbatim shape from the live endpoint."""
    body = {
        "success": False,
        "message": "Email or password incorrect.",
        "errors": {"email": ["Email or password incorrect."]},
    }
    async with responding(422, body) as client:
        with pytest.raises(LoginFailed, match="Email or password incorrect"):
            await login("max@example.com", "wrong", client)


async def test_a_field_error_is_used_when_there_is_no_top_level_message():
    body = {"success": False, "errors": {"password": ["The field is required."]}}
    async with responding(422, body) as client:
        with pytest.raises(LoginFailed, match="The field is required"):
            await login("max@example.com", "", client)


async def test_rate_limiting_says_to_wait_rather_than_retry():
    """Weeek advertises x-ratelimit-limit: 5 on this endpoint."""
    async with responding(429, {"message": "Too Many Attempts."}) as client:
        with pytest.raises(LoginFailed, match="rate limiting"):
            await login("max@example.com", "s3cret", client)


async def test_an_accepted_sign_in_with_no_session_cookie_points_at_the_manual_route():
    """What a 2FA or SSO account would look like: accepted, but no session issued."""
    async with responding(200, {"success": True}) as client:
        with pytest.raises(LoginFailed, match="two-factor authentication or SSO"):
            await login("max@example.com", "s3cret", client)


async def test_a_captcha_page_is_reported_as_a_login_failure_not_a_parse_error():
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            403, content=b"<html>are you a robot</html>", headers={"content-type": "text/html"}
        )

    async with client_returning(handler) as client:
        with pytest.raises(LoginFailed):
            await login("max@example.com", "s3cret", client)
