"""Where downloaded attachments land."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .detect import extension_for, mime_for_extension

ROOT = Path("/tmp/weeek-mcp")
MAX_AGE_SECONDS = 24 * 3600

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STEM = 100


def task_dir(task_id: int) -> Path:
    path = ROOT / str(task_id)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def sweep(now: float | None = None) -> None:
    if not ROOT.is_dir():
        return
    cutoff = (now or time.time()) - MAX_AGE_SECONDS
    for child in ROOT.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def save(directory: Path, name: str, data: bytes, mime: str | None = None) -> Path:
    path = _unique(directory, safe_name(name, mime))
    path.write_bytes(data)
    return path


def safe_name(name: str, mime: str | None = None) -> str:
    """Sanitise a Weeek-supplied name. Sanitising can eat the whole extension,
    so it is restored from `mime`."""
    raw = Path(name.strip()).name  # anyone who can see the task can set a name
    stem, dot, extension = raw.rpartition(".")
    if not dot:
        stem, extension = raw, ""

    stem = _UNSAFE.sub("_", stem).strip("._")[:_MAX_STEM] or "attachment"
    extension = _UNSAFE.sub("", extension).lower()

    if extension and mime_for_extension(extension) == mime:
        return f"{stem}.{extension}"

    preferred = extension_for(mime)
    if preferred:
        return stem + preferred
    return f"{stem}.{extension}" if extension else stem


def _unique(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    base = Path(name).stem
    suffix = Path(name).suffix
    for index in range(2, 1000):
        candidate = directory / f"{base}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"could not find a free filename for {name!r} in {directory}")
