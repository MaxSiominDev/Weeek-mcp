"""Fetch a task's files onto disk. One unreadable file must not sink the task,
so every failure becomes a note instead of an exception."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx2

from ..session.client import SessionApi
from ..session.prosemirror import ImageRef
from . import store
from .detect import detect_mime, is_viewable

MAX_BYTES = 25 * 1024 * 1024

# Linked, not stored: our session has no authority on those services.
EXTERNAL_SERVICES = frozenset({"google_drive", "dropbox", "one_drive", "box"})


@dataclass(frozen=True)
class Downloaded:
    name: str
    path: Path | None = None
    mime: str | None = None
    size: int = 0
    url: str | None = None
    skipped: str | None = None
    # Files hosted elsewhere. Weeek's own URLs are credentials, never rendered.
    external: bool = False

    @property
    def viewable(self) -> bool:
        return self.path is not None and is_viewable(self.mime)


async def fetch_attachments(
    api: SessionApi, files: list[dict], directory: Path
) -> list[Downloaded]:
    results: list[Downloaded] = []
    for record in files:
        if not isinstance(record, dict):
            continue
        results.append(await _fetch_attachment(api, record, directory))
    return results


async def _fetch_attachment(api: SessionApi, record: dict, directory: Path) -> Downloaded:
    name = str(record.get("name") or "attachment")
    service = record.get("service")
    if service in EXTERNAL_SERVICES:
        return Downloaded(
            name=name,
            skipped=f"stored in {service}, which this session cannot read",
            external=True,
        )

    url = record.get("downloadLink")
    if not url:
        return Downloaded(name=name, skipped="no download link in the file record")

    declared_size = record.get("size")
    if isinstance(declared_size, int) and declared_size > MAX_BYTES:
        return Downloaded(name=name, size=declared_size, url=url, skipped=_too_big(declared_size))

    try:
        response = await api.download(str(url))
    except Exception as exc:  # noqa: BLE001
        return Downloaded(name=name, url=url, skipped=f"download failed ({exc})")

    return _store(
        response,
        name=name,
        directory=directory,
        url=str(url),
        declared_mime=str(record.get("mimeType") or ""),
    )


async def fetch_comment_images(
    api: SessionApi, images: list[ImageRef], directory: Path
) -> dict[str, Downloaded]:
    seen: dict[str, Downloaded] = {}
    for image in images:
        if image.link in seen:
            continue
        seen[image.link] = await _fetch_comment_image(api, image, directory)
    return seen


async def _fetch_comment_image(api: SessionApi, image: ImageRef, directory: Path) -> Downloaded:
    name = image.name or _name_from_url(image.link)
    if isinstance(image.size, int) and image.size > MAX_BYTES:
        return Downloaded(name=name, size=image.size, url=image.link, skipped=_too_big(image.size))

    try:
        response = await api.download(image.link)
    except Exception as exc:  # noqa: BLE001
        return Downloaded(name=name, url=image.link, skipped=f"download failed ({exc})")

    return _store(response, name=name, directory=directory, url=image.link)


def _store(
    response: httpx2.Response,
    *,
    name: str,
    directory: Path,
    url: str,
    declared_mime: str = "",
) -> Downloaded:
    if response.status_code != 200:
        return Downloaded(name=name, url=url, skipped=f"HTTP {response.status_code}")

    data = response.content
    if len(data) > MAX_BYTES:
        return Downloaded(name=name, size=len(data), url=url, skipped=_too_big(len(data)))
    if not data:
        return Downloaded(name=name, url=url, skipped="empty response")

    mime = detect_mime(data, name, response.headers.get("content-type") or declared_mime)
    path = store.save(directory, name, data, mime)
    if not is_viewable(mime):
        # Written out anyway, but not offered as an image.
        return Downloaded(
            name=name,
            path=path,
            mime=mime,
            size=len(data),
            url=url,
            skipped=f"{mime or 'unrecognised format'} cannot be viewed as an image",
        )

    return Downloaded(name=name, path=path, mime=mime, size=len(data), url=url)


def _too_big(size: int) -> str:
    return f"{size / 1_048_576:.1f} MB exceeds the {MAX_BYTES // 1_048_576} MB download limit"


def _name_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    return tail or "image"
