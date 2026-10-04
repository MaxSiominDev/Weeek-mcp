"""The skip paths: one unreadable file must never sink the whole task."""

from __future__ import annotations

import httpx2
import pytest

from conftest import client_returning
from weeek_mcp.files import download, store
from weeek_mcp.session.client import SessionApi
from weeek_mcp.session.prosemirror import ImageRef

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"
LINK = "https://api.weeek.net/ws/424242/files/att-1"


@pytest.fixture
def directory(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "weeek-mcp")
    return store.task_dir(154)


def record(**overrides) -> dict:
    return {
        "id": "f1",
        "name": "shot.png",
        "service": "weeek",
        "size": len(PNG),
        "downloadLink": LINK,
        "mimeType": "image/png",
        **overrides,
    }


def serve(payload: bytes = PNG, status: int = 200, content_type: str = "image/png"):
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, content=payload, headers={"content-type": content_type})

    return handler


async def fetch(handler, files, directory) -> list[download.Downloaded]:
    async with client_returning(handler) as client:
        api = SessionApi({"weeek_session": "s"}, client)
        return await download.fetch_attachments(api, files, directory)


async def test_a_file_on_an_external_service_is_linked_not_fetched(directory):
    files = [record(service="dropbox", name="spec.doc", downloadLink=None)]

    def refuse(request):
        raise AssertionError(f"nothing should be requested, got {request.url}")

    [result] = await fetch(refuse, files, directory)

    assert result.path is None
    assert result.external is True
    assert "dropbox" in result.skipped


async def test_a_record_without_a_download_link_is_skipped(directory):
    [result] = await fetch(serve(), [record(downloadLink=None)], directory)

    assert result.path is None
    assert "no download link" in result.skipped


async def test_a_size_weeek_declares_as_oversized_is_never_downloaded(directory, monkeypatch):
    monkeypatch.setattr(download, "MAX_BYTES", 1024)

    def refuse(request):
        raise AssertionError("must not download a file already known to be too big")

    [result] = await fetch(refuse, [record(size=99_000_000)], directory)

    assert result.path is None
    assert "exceeds" in result.skipped


async def test_a_body_larger_than_declared_is_still_caught(directory, monkeypatch):
    monkeypatch.setattr(download, "MAX_BYTES", 8)

    [result] = await fetch(serve(), [record(size=4)], directory)

    assert result.path is None
    assert "exceeds" in result.skipped


async def test_a_failed_download_is_reported_by_status(directory):
    [result] = await fetch(serve(b"gone", status=403), [record()], directory)

    assert result.path is None
    assert "HTTP 403" in result.skipped


async def test_an_empty_body_is_not_written(directory):
    [result] = await fetch(serve(b""), [record()], directory)

    assert result.path is None
    assert "empty" in result.skipped


async def test_an_svg_is_saved_but_never_offered_as_viewable(directory):
    """Claude rejects SVG outright, and Weeek does serve it."""
    [result] = await fetch(
        serve(SVG, content_type="image/svg+xml"), [record(name="chart.svg")], directory
    )

    assert result.path is not None and result.path.exists()
    assert result.viewable is False
    assert "cannot be viewed" in result.skipped


async def test_an_html_error_page_served_with_a_png_name_is_not_called_an_image(directory):
    [result] = await fetch(
        serve(b"<!DOCTYPE html><html>nope</html>", content_type="text/html"),
        [record()],
        directory,
    )

    assert result.viewable is False


async def test_a_successful_image_records_its_type_and_size(directory):
    [result] = await fetch(serve(), [record()], directory)

    assert result.viewable is True
    assert result.mime == "image/png"
    assert result.size == len(PNG)
    assert result.path.read_bytes() == PNG


async def test_the_declared_type_fills_in_when_the_response_ships_none(directory):
    """The files listing knows the MIME type; a bare response must not reduce the
    decision to guessing from the file name."""

    def bare(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=PNG)

    [result] = await fetch(bare, [record(name="shot", mimeType="image/png")], directory)

    assert result.viewable is True
    assert result.mime == "image/png"


async def test_the_session_cookie_travels_with_attachment_downloads(recorded, directory):
    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return httpx2.Response(200, content=PNG, headers={"content-type": "image/png"})

    async with client_returning(handler) as client:
        api = SessionApi({"weeek_session": "abc"}, client)
        await download.fetch_attachments(api, [record()], directory)

    assert "weeek_session=abc" in recorded[0].headers["cookie"]


async def test_a_redirect_off_weeek_carries_no_credentials(directory):
    """Pins the httpx2 redirect behaviour the whole design rests on."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.host == "api.weeek.net":
            return httpx2.Response(
                303, headers={"location": "https://storage.example.com/f.png?X-Amz-Signature=sig"}
            )
        return httpx2.Response(200, content=PNG, headers={"content-type": "image/png"})

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), follow_redirects=True
    ) as client:
        api = SessionApi({"weeek_session": "abc"}, client)
        [result] = await download.fetch_attachments(api, [record()], directory)

    assert result.viewable is True
    [first, second] = seen
    assert first.url.host == "api.weeek.net"
    assert second.url.host == "storage.example.com"
    assert "cookie" not in second.headers
    assert "authorization" not in second.headers


async def test_one_broken_attachment_does_not_stop_the_others(directory):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("bad"):
            return httpx2.Response(500)
        return httpx2.Response(200, content=PNG, headers={"content-type": "image/png"})

    files = [record(id="bad", name="bad.png", downloadLink=LINK + "bad"), record()]
    broken, fine = await fetch(handler, files, directory)

    assert broken.path is None
    assert fine.viewable is True


async def test_the_same_comment_image_is_only_downloaded_once(directory):
    calls = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, content=PNG, headers={"content-type": "image/png"})

    link = "https://api.weeek.net/ws/424242/files/dup"
    async with client_returning(handler) as client:
        api = SessionApi({"weeek_session": "s"}, client)
        results = await download.fetch_comment_images(
            api, [ImageRef(link, "a.png"), ImageRef(link, "a.png")], directory
        )

    assert calls == 1
    assert set(results) == {link}


async def test_a_comment_image_that_fails_is_reported_not_raised(directory):
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("gone")

    async with client_returning(handler) as client:
        api = SessionApi({"weeek_session": "s"}, client)
        results = await download.fetch_comment_images(
            api, [ImageRef("https://api.weeek.net/ws/1/files/x", "a.png")], directory
        )

    [result] = results.values()
    assert result.path is None
    assert "download failed" in result.skipped


async def test_an_unnamed_comment_image_falls_back_to_its_url(directory):
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=PNG, headers={"content-type": "image/png"})

    async with client_returning(handler) as client:
        api = SessionApi({"weeek_session": "s"}, client)
        results = await download.fetch_comment_images(
            api, [ImageRef("https://api.weeek.net/ws/1/files/9f3c-uuid")], directory
        )

    [result] = results.values()
    # Named from the URL and given the extension its bytes call for, so the file
    # is opened as an image rather than as text.
    assert result.path.name == "9f3c-uuid.png"
