"""Working out what a downloaded file actually is."""

from __future__ import annotations

from pathlib import PurePosixPath

# No SVG: Claude rejects it, Weeek does serve it.
VIEWABLE = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}


def detect_mime(data: bytes, filename: str = "", declared: str = "") -> str | None:
    # Name last: an error page served as shot.png must not pass for an image.
    sniffed = _sniff(data)
    if sniffed:
        return sniffed

    served = declared.split(";")[0].strip().lower()
    if served and served != "application/octet-stream":
        return served

    extension = PurePosixPath(filename).suffix.lower()
    return _BY_EXTENSION.get(extension)


def is_viewable(mime: str | None) -> bool:
    return mime in VIEWABLE


def extension_for(mime: str | None) -> str:
    for suffix, known in _BY_EXTENSION.items():
        if known == mime:
            return suffix
    return ""


def mime_for_extension(extension: str) -> str | None:
    return _BY_EXTENSION.get(f".{extension.lstrip('.').lower()}")


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"

    head = data[:512].lstrip()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:1024]):
        return "image/svg+xml"
    return None
