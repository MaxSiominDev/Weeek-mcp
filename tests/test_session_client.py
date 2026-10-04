import httpx2
import pytest

from conftest import UNAUTHENTICATED_BODY, client_returning, html_response, json_response
from weeek_mcp.errors import SessionExpired, TaskNotFound, UnexpectedResponse
from weeek_mcp.session.client import SessionApi

COOKIES = {"weeek_session": "abc", "remember_app_59ba": "xyz"}


async def test_dead_session_returns_http_200_and_must_still_be_detected():
    """The trap: an expired session answers HTTP 200 with a failure envelope."""
    api = SessionApi(COOKIES, client_returning(lambda _: json_response(UNAUTHENTICATED_BODY)))

    with pytest.raises(SessionExpired):
        await api.task_with_comments(424242, 154)


async def test_outright_401_is_also_a_dead_session():
    api = SessionApi(COOKIES, client_returning(lambda _: json_response(UNAUTHENTICATED_BODY, 401)))

    with pytest.raises(SessionExpired):
        await api.task_with_comments(424242, 154)


async def test_live_session_returns_the_task():
    payload = {"success": True, "task": {"id": 154, "commentsCount": 1, "comments": [{"id": 1}]}}
    api = SessionApi(COOKIES, client_returning(lambda _: json_response(payload)))

    task = await api.task_with_comments(424242, 154)

    assert task["id"] == 154
    assert len(task["comments"]) == 1


async def test_request_carries_the_cookie_and_browser_referer(recorded):
    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return json_response({"success": True, "task": {"id": 154}})

    await SessionApi(COOKIES, client_returning(handler)).task_with_comments(424242, 154)

    sent = recorded[0]
    assert "weeek_session=abc" in sent.headers["cookie"]
    assert "remember_app_59ba=xyz" in sent.headers["cookie"]
    assert sent.headers["referer"] == "https://app.weeek.net/"
    assert sent.url.path == "/ws/424242/tm/tasks/154"
    assert sent.url.params["withSubtasks"] == "1"


async def test_html_error_page_does_not_surface_as_a_json_parse_error():
    api = SessionApi(COOKIES, client_returning(lambda _: html_response()))

    with pytest.raises(UnexpectedResponse, match="rather than JSON"):
        await api.task_with_comments(424242, 154)


async def test_missing_task_in_a_successful_envelope():
    api = SessionApi(COOKIES, client_returning(lambda _: json_response({"success": True})))

    with pytest.raises(TaskNotFound):
        await api.task_with_comments(424242, 154)


async def test_a_404_on_the_task_names_the_id():
    api = SessionApi(
        COOKIES,
        client_returning(lambda _: json_response({"success": False, "code": 1234}, 404)),
    )

    with pytest.raises(TaskNotFound, match="154"):
        await api.task_with_comments(424242, 154)


async def test_the_file_list_is_unwrapped_from_its_own_call(recorded):
    payload = {"success": True, "files": [{"id": "f1", "name": "shot.png"}]}

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return json_response(payload)

    files = await SessionApi(COOKIES, client_returning(handler)).task_files(424242, 154)

    assert files[0]["name"] == "shot.png"
    assert recorded[0].url.path == "/ws/424242/tm/tasks/154/files"


async def test_members_come_under_the_data_key(recorded):
    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return json_response({"success": True, "data": [{"id": "u1", "firstName": "Max"}]})

    members = await SessionApi(COOKIES, client_returning(handler)).members(424242)

    assert members[0]["firstName"] == "Max"
    assert recorded[0].url.path == "/ws/424242/members"


async def test_projects_are_unwrapped(recorded):
    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return json_response({"success": True, "projects": [{"id": 1, "name": "Mobile"}]})

    projects = await SessionApi(COOKIES, client_returning(handler)).projects(424242)

    assert projects[0]["name"] == "Mobile"
    assert recorded[0].url.path == "/ws/424242/tm/projects"


async def test_a_reissued_session_cookie_is_adopted():
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=b'{"success": true, "task": {"id": 154}}',
            headers=[
                ("content-type", "application/json"),
                ("set-cookie", "weeek_session=reissued; Max-Age=7200; path=/"),
            ],
        )

    api = SessionApi(COOKIES, client_returning(handler))
    await api.task_with_comments(424242, 154)

    assert api.refreshed is True
    assert api.cookies["weeek_session"] == "reissued"
    # The remember-me cookie we started with must survive the swap.
    assert api.cookies["remember_app_59ba"] == "xyz"


async def test_an_unchanged_session_is_not_reported_as_refreshed():
    api = SessionApi(COOKIES, client_returning(lambda _: json_response({"success": True, "task": {}})))
    await api.workspaces()

    assert api.refreshed is False


async def test_the_reissued_cookie_is_used_for_the_next_request(recorded):
    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        headers = [("content-type", "application/json")]
        if len(recorded) == 1:
            headers.append(("set-cookie", "weeek_session=reissued; path=/"))
        return httpx2.Response(200, content=b'{"success": true, "task": {"id": 1}}', headers=headers)

    api = SessionApi(COOKIES, client_returning(handler))
    await api.task_with_comments(424242, 154)
    await api.download("https://api.weeek.net/ws/424242/files/x")

    assert "weeek_session=reissued" in recorded[1].headers["cookie"]


async def test_file_download_sends_the_cookie(recorded):
    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return httpx2.Response(200, content=b"\x89PNG")

    api = SessionApi(COOKIES, client_returning(handler))
    await api.download("https://api.weeek.net/ws/424242/files/uuid")

    assert "weeek_session=abc" in recorded[0].headers["cookie"]
