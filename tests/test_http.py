import httpx2
import pytest

from conftest import client_returning, json_response
from weeek_mcp import http
from weeek_mcp.errors import UnexpectedResponse


async def responder(codes: list[int]):
    """Answers with each status in turn, so a retry gets a different result."""
    remaining = list(codes)
    seen: list[int] = []

    def handler(_request: httpx2.Request) -> httpx2.Response:
        code = remaining.pop(0) if remaining else 200
        seen.append(code)
        return json_response({"success": True}, code)

    return handler, seen


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_transient_failures_are_retried_until_they_succeed(status):
    handler, seen = await responder([status, 200])

    async with client_returning(handler) as client:
        response = await http.request(client, "GET", "https://api.weeek.net/x")

    assert response.status_code == 200
    assert seen == [status, 200]


async def test_a_persistently_failing_status_is_returned_rather_than_raised():
    handler, seen = await responder([503, 503, 503])

    async with client_returning(handler) as client:
        response = await http.request(client, "GET", "https://api.weeek.net/x")

    assert response.status_code == 503
    assert len(seen) == 3  # three attempts, then give up


@pytest.mark.parametrize("status", [200, 400, 404, 422])
async def test_settled_outcomes_are_not_retried(status):
    handler, seen = await responder([status, 200])

    async with client_returning(handler) as client:
        await http.request(client, "GET", "https://api.weeek.net/x")

    assert seen == [status]


async def test_transport_errors_are_retried_then_re_raised():
    attempts = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        raise httpx2.ConnectError("network down")

    async with client_returning(handler) as client:
        with pytest.raises(httpx2.TransportError):
            await http.request(client, "GET", "https://api.weeek.net/x")

    assert attempts == 3


async def test_a_transport_error_that_clears_up_succeeds():
    attempts = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx2.ConnectError("network blip")
        return json_response({"success": True})

    async with client_returning(handler) as client:
        response = await http.request(client, "GET", "https://api.weeek.net/x")

    assert response.status_code == 200


def test_failure_code_only_reports_on_an_explicit_failure():
    assert http.failure_code({"success": False, "code": 2000000}) == http.UNAUTHENTICATED
    assert http.failure_code({"success": True, "task": {}}) is None
    # A failure without a numeric code must still register as a failure.
    assert http.failure_code({"success": False}) == -1


@pytest.mark.parametrize("body", [b"[1, 2]", b"not json", b'"a string"'])
def test_a_body_that_is_not_an_envelope_object_is_rejected(body):
    response = httpx2.Response(
        200,
        content=body,
        headers={"content-type": "application/json"},
        request=httpx2.Request("GET", "https://api.weeek.net/x"),
    )

    with pytest.raises(UnexpectedResponse, match="rather than JSON"):
        http.envelope(response)
