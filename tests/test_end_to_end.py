"""The whole pipeline: a pasted link in, Markdown plus files on disk out."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx2
import pytest

from conftest import client_returning, json_response
from weeek_mcp import service
from weeek_mcp.config import Config
from weeek_mcp.errors import SessionExpired, TaskNotFound, WeeekError
from weeek_mcp.files import store
from weeek_mcp.session import credentials, storage
from weeek_mcp.session.storage import StoredSession

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
URL = (
    "https://app.weeek.net/ws/424242/project/1/board/1"
    "?modals=m_task&m_task_workspace-id=424242&m_task_id=154"
)

COMMENT_IMAGE = "https://api.weeek.net/ws/424242/files/img-uuid"
DESCRIPTION_IMAGE = "https://api.weeek.net/ws/424242/files/body-img-uuid"
ATTACHMENT_LINK = "https://api.weeek.net/ws/424242/files/att-uuid"


def doc(*blocks: dict) -> dict:
    return {"version": 1, "data": {"type": "doc", "content": list(blocks)}}


def paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


INTERNAL_TASK = {
    "success": True,
    "task": {
        "id": 154,
        "title": "Login screen falls over on rotate",
        "content": doc(
            paragraph("Steps to reproduce are in the comments."),
            {"type": "image", "attrs": {"link": DESCRIPTION_IMAGE, "name": "body-shot.png"}},
        ),
        "priority": 2,
        "type": "action",
        "completed": False,
        "authorId": "user-a",
        "assignees": ["user-b"],
        "locations": [{"projectId": 1, "boardColumnId": 3}],
        "createdAt": "2026-07-29T10:00:00+00:00",
        "startDateTime": "2026-08-01T09:00:00Z",
        "dueDateTime": "2026-08-10T18:00:00Z",
        "commentsCount": 2,
        "comments": [
            {
                "id": 1,
                "parentId": None,
                "userId": "user-b",
                "sentAt": "2026-07-29T10:58:20Z",
                "user": {"id": "user-b", "name": "Olga Bajwa", "email": "o@example.com"},
                "content": doc(
                    paragraph("Here:"),
                    {"type": "image", "attrs": {"link": COMMENT_IMAGE, "name": "shot.png"}},
                ),
            },
            {
                "id": 2,
                "parentId": 1,
                "userId": "user-a",
                "sentAt": "2026-07-29T11:10:00Z",
                "isUpdated": True,
                "content": doc(
                    {
                        "type": "code",
                        "attrs": {"language": "kotlin"},
                        "content": [{"type": "text", "text": "val x = 1"}],
                    }
                ),
            },
        ],
    },
    "subTasks": [],
}

FILES = {
    "success": True,
    "files": [
        {
            "id": "att-uuid",
            "name": "diagram.png",
            "service": "weeek",
            "size": len(PNG),
            "downloadLink": ATTACHMENT_LINK,
            "mimeType": "image/png",
        },
        {"id": "ext-uuid", "name": "spec.doc", "service": "google_drive", "size": 4096},
    ],
}

MEMBERS = {
    "success": True,
    "data": [
        {"id": "user-a", "firstName": "Max", "lastName": "Semin", "email": "m@example.com"},
        {"id": "user-b", "firstName": "Olga", "lastName": "Bajwa", "email": "o@example.com"},
    ],
}

PROJECTS = {"success": True, "projects": [{"id": 1, "name": "Mobile"}]}


# Recorded outside the handler: the download layer catches exceptions per file,
# so an assert in there would be swallowed into a "download failed" note.
SEEN: list[httpx2.Request] = []


def handler(request: httpx2.Request) -> httpx2.Response:
    SEEN.append(request)
    path = request.url.path

    if path == "/ws/424242/files/img-uuid":
        return png(COMMENT_IMAGE)
    if path == "/ws/424242/files/body-img-uuid":
        return png(DESCRIPTION_IMAGE)
    if path == "/ws/424242/files/att-uuid":
        return png(ATTACHMENT_LINK)
    if path == "/ws/424242/tm/tasks/154":
        return json_response(INTERNAL_TASK)
    if path == "/ws/424242/tm/tasks/154/files":
        return json_response(FILES)
    if path == "/ws/424242/members":
        return json_response(MEMBERS)
    if path == "/ws/424242/tm/projects":
        return json_response(PROJECTS)
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


def png(link: str) -> httpx2.Response:
    return httpx2.Response(200, content=PNG, headers={"content-type": "image/png", "x-link": link})


@pytest.fixture
def config():
    return Config(
        session=StoredSession(
            cookies={"weeek_session": "abc"},
            stored_at=datetime.now(UTC),
            workspace_id=424242,
        ),
    )


@pytest.fixture(autouse=True)
def isolated_root(tmp_path, monkeypatch):
    SEEN.clear()
    monkeypatch.setattr(store, "ROOT", tmp_path / "weeek-mcp")


def sent_to(predicate) -> list[httpx2.Request]:
    return [r for r in SEEN if predicate(r)]


async def rendered(config) -> str:
    async with client_returning(handler) as client:
        return await service.get_task(URL, config, client=client)


async def test_a_missing_task_propagates_while_siblings_still_settle(config):
    def task_missing(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/ws/424242/tm/tasks/154":
            return json_response({"success": False, "code": 404, "message": "not found"}, 404)
        return handler(request)

    async with client_returning(task_missing) as client:
        with pytest.raises(TaskNotFound, match="154"):
            await service.get_task(URL, config, client=client)

    # The lookup siblings were awaited to completion, not abandoned mid-flight.
    assert sent_to(lambda r: r.url.path == "/ws/424242/members")
    assert sent_to(lambda r: r.url.path == "/ws/424242/tm/projects")
    assert sent_to(lambda r: r.url.path == "/ws/424242/tm/tasks/154/files")


async def test_title_description_and_resolved_names(config):
    out = await rendered(config)

    assert "# Login screen falls over on rotate" in out
    assert "Steps to reproduce are in the comments." in out
    assert "**Priority:** High" in out
    assert "**Project:** Mobile" in out
    assert "**Dates:** starts 2026-08-01 09:00:00, due 2026-08-10 18:00:00, created 2026-07-29 10:00:00" in out
    # UUIDs must never reach the reader.
    assert "**Assignees:** Olga Bajwa" in out
    assert "**Author:** Max Semin" in out
    assert "user-a" not in out
    assert "user-b" not in out


async def test_an_image_inside_the_description_is_downloaded_and_linked_there(config, tmp_path):
    out = await rendered(config)

    saved = tmp_path / "weeek-mcp" / "154" / "body-shot.png"
    assert saved.read_bytes() == PNG
    description = out.split("## Description")[1].split("##")[0]
    assert f"[body-shot.png: open `{saved}` with Read]" in description


async def test_comments_are_rendered_in_order_with_authors(config):
    out = await rendered(config)

    assert "## Comments (2)" in out
    assert "### Olga Bajwa, 2026-07-29 10:58:20" in out
    assert "(edited)" in out
    assert "_in reply to Olga Bajwa_" in out
    # The code block that the other open-source converter silently loses.
    assert "```kotlin\nval x = 1\n```" in out


async def test_attachment_is_downloaded_and_pointed_at(config, tmp_path):
    out = await rendered(config)

    saved = tmp_path / "weeek-mcp" / "154" / "diagram.png"
    assert saved.read_bytes() == PNG
    assert str(saved) in out
    assert "Open them with the Read tool" in out


async def test_comment_image_is_downloaded_and_linked_in_place(config, tmp_path):
    out = await rendered(config)

    saved = tmp_path / "weeek-mcp" / "154" / "shot.png"
    assert saved.read_bytes() == PNG
    # Referenced inside the comment, not collected into a trailing list.
    body = out.split("### Olga Bajwa")[1]
    assert f"`{saved}`" in body.split("###")[0]


async def test_every_request_carries_the_session_and_never_a_token(config):
    await rendered(config)

    assert SEEN, "the pipeline made no requests at all"
    for request in SEEN:
        assert request.url.host == "api.weeek.net"
        assert "weeek_session=abc" in request.headers.get("cookie", "")
        assert "authorization" not in request.headers


async def test_external_attachment_is_reported_not_fetched(config):
    out = await rendered(config)

    assert "spec.doc" in out
    assert "google_drive" in out


async def test_comment_count_mismatch_is_surfaced(config):
    shrunk = json.loads(json.dumps(INTERNAL_TASK))
    shrunk["task"]["commentsCount"] = 7

    def truncating(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/ws/424242/tm/tasks/154":
            return json_response(shrunk)
        return handler(request)

    async with client_returning(truncating) as client:
        out = await service.get_task(URL, config, client=client)

    assert "Weeek reports 7 comments but returned 2" in out


async def test_an_expired_session_is_renewed_mid_request(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(credentials, "password_for", lambda email: "s3cret")

    stale = Config(
        session=StoredSession(
            cookies={"weeek_session": "stale"},
            stored_at=datetime.now(UTC),
            workspace_id=424242,
            email="max@example.com",
        ),
    )
    attempts = {"task": 0, "logins": 0}

    def handler_with_expiry(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/auth/login":
            attempts["logins"] += 1
            return httpx2.Response(
                200,
                content=b'{"success": true}',
                headers=[
                    ("content-type", "application/json"),
                    ("set-cookie", "weeek_session=renewed; Max-Age=7200; path=/"),
                ],
            )
        if request.url.path == "/ws/424242/tm/tasks/154":
            attempts["task"] += 1
            if attempts["task"] == 1:
                return json_response({"success": False, "code": 2000000, "message": "Unauthenticated."})
        return handler(request)

    async with client_returning(handler_with_expiry) as client:
        out = await service.get_task(URL, stale, client=client)

    assert attempts["logins"] == 1
    assert attempts["task"] == 2
    assert "## Comments (2)" in out


async def test_a_reissued_cookie_is_written_back_to_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    sso = Config(
        session=StoredSession(
            cookies={"weeek_session": "old", "remember_app_59ba": "keepme"},
            stored_at=datetime.now(UTC),
            workspace_id=424242,
        ),
    )

    def reissuing(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/ws/424242/tm/tasks/154":
            return httpx2.Response(
                200,
                content=json.dumps(INTERNAL_TASK).encode(),
                headers=[
                    ("content-type", "application/json"),
                    ("set-cookie", "weeek_session=reissued; Max-Age=7200; path=/"),
                ],
            )
        return handler(request)

    async with client_returning(reissuing) as client:
        await service.get_task(URL, sso, client=client)

    saved = storage.load()
    assert saved.cookies["weeek_session"] == "reissued"
    assert saved.cookies["remember_app_59ba"] == "keepme"


async def test_an_ephemeral_env_cookie_is_never_written_to_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    env_session = Config(
        session=StoredSession(
            cookies={"weeek_session": "env", "remember_app_59ba": "keepme"},
            stored_at=datetime.now(UTC),
            workspace_id=424242,
            ephemeral=True,
        ),
    )

    def reissuing(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/ws/424242/tm/tasks/154":
            return httpx2.Response(
                200,
                content=json.dumps(INTERNAL_TASK).encode(),
                headers=[
                    ("content-type", "application/json"),
                    ("set-cookie", "weeek_session=reissued; Max-Age=7200; path=/"),
                ],
            )
        return handler(request)

    async with client_returning(reissuing) as client:
        await service.get_task(URL, env_session, client=client)

    assert storage.load() is None
    assert not storage.session_path().exists()


async def test_a_dead_browser_session_is_re_read_from_the_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    from weeek_mcp.session import browser

    reads = {"count": 0}

    def fake_extract(which):
        reads["count"] += 1
        assert which == "chrome"
        return {"weeek_session": "from-chrome"}

    monkeypatch.setattr(browser, "extract", fake_extract)

    dead = Config(
        session=StoredSession(
            cookies={"weeek_session": "dead"},
            stored_at=datetime.now(UTC),
            workspace_id=424242,
            browser="chrome",
        ),
    )
    first = {"seen": False}

    def expiring_once(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/ws/424242/tm/tasks/154" and not first["seen"]:
            first["seen"] = True
            return json_response({"success": False, "code": 2000000, "message": "Unauthenticated."})
        return handler(request)

    async with client_returning(expiring_once) as client:
        out = await service.get_task(URL, dead, client=client)

    assert reads["count"] == 1
    assert "## Comments (2)" in out
    # The retry must actually use the re-read cookie, and it must be persisted.
    retries = sent_to(lambda r: r.url.path == "/ws/424242/tm/tasks/154")
    assert "weeek_session=from-chrome" in retries[-1].headers.get("cookie", "")
    saved = storage.load()
    assert saved.cookies["weeek_session"] == "from-chrome"
    assert saved.browser == "chrome"


async def test_a_browser_reread_that_is_also_dead_gives_browser_specific_advice(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from weeek_mcp.session import browser

    monkeypatch.setattr(browser, "extract", lambda which: {"weeek_session": "also-dead"})
    stored = storage.save({"weeek_session": "original"}, workspace_id=424242, browser="chrome")

    dead = Config(
        session=StoredSession(
            cookies={"weeek_session": "dead"},
            stored_at=datetime.now(UTC),
            workspace_id=424242,
            browser="chrome",
        ),
    )

    def always_expired(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/ws/424242/tm/tasks/154":
            return json_response({"success": False, "code": 2000000, "message": "Unauthenticated."})
        return handler(request)

    async with client_returning(always_expired) as client:
        with pytest.raises(WeeekError, match=r"app\.weeek\.net in chrome"):
            await service.get_task(URL, dead, client=client)

    # The good-ish stored cookie is left untouched by the failed renewal.
    assert storage.load().cookies["weeek_session"] == "original"
    assert stored.exists()


async def test_a_pasted_cookie_that_expires_cannot_silently_carry_on(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    no_email = Config(
        session=StoredSession(
            cookies={"weeek_session": "stale"},
            stored_at=datetime.now(UTC),
            workspace_id=424242,
        ),
    )

    def always_expired(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/ws/424242/tm/tasks/154":
            return json_response({"success": False, "code": 2000000, "message": "Unauthenticated."})
        return handler(request)

    async with client_returning(always_expired) as client:
        with pytest.raises(SessionExpired, match="weeek-mcp login"):
            await service.get_task(URL, no_email, client=client)


async def test_the_client_service_builds_itself_follows_redirects(config, monkeypatch):
    # The only test that exercises the client service builds itself.
    seen: list[httpx2.Request] = []
    setup: dict = {}

    def redirecting(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/ws/424242/files/att-uuid" and "hop" not in request.url.params:
            return httpx2.Response(303, headers={"location": ATTACHMENT_LINK + "?hop=2"})
        return handler(request)

    real = httpx2.AsyncClient

    def factory(**kwargs):
        setup.update(kwargs)
        return real(
            transport=httpx2.MockTransport(redirecting),
            timeout=kwargs["timeout"],
            follow_redirects=kwargs["follow_redirects"],
        )

    # service looks AsyncClient up on the shared httpx2 module at call time.
    monkeypatch.setattr(httpx2, "AsyncClient", factory)

    out = await service.get_task(URL, config)

    assert setup["follow_redirects"] is True
    assert any(r.url.params.get("hop") == "2" for r in seen)
    assert "diagram.png" in out


async def test_a_bare_task_id_uses_the_stored_workspace(config):
    async with client_returning(handler) as client:
        out = await service.get_task("154", config, client=client)

    assert "# Login screen falls over on rotate" in out
