"""Read and write the stored session."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .cookies import parse_cookie_header, to_header


@dataclass(frozen=True)
class StoredSession:
    cookies: dict[str, str]
    stored_at: datetime
    workspace_id: int | None = None
    # A password login: the server can sign in again when the session lapses.
    email: str | None = None
    # A browser login: the browser to re-read when the cookie dies.
    browser: str | None = None
    # A WEEEK_COOKIE override must never be written to disk.
    ephemeral: bool = False

    @property
    def age_hours(self) -> float:
        return (datetime.now(UTC) - self.stored_at).total_seconds() / 3600

    @property
    def renewable(self) -> bool:
        return self.email is not None or self.browser is not None


def session_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "weeek-mcp" / "session"


def save(
    cookies: dict[str, str],
    *,
    workspace_id: int | None = None,
    email: str | None = None,
    browser: str | None = None,
) -> Path:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    payload = {
        "cookie": to_header(cookies),
        "stored_at": datetime.now(UTC).isoformat(),
        "workspace_id": workspace_id,
        "email": email,
        "browser": browser,
    }
    # The cookie is a live login, and os.open's mode only applies on create.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "w")
    except BaseException:
        os.close(fd)
        raise

    with handle as fh:
        json.dump(payload, fh, indent=2)
    return path


def load() -> StoredSession | None:
    path = session_path()
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("cookie"), str):
        # A mangled file reads as no session.
        return None

    try:
        jar = parse_cookie_header(payload["cookie"])
        stored_at = datetime.fromisoformat(payload["stored_at"])
    except (KeyError, ValueError, TypeError):
        return None

    return StoredSession(
        cookies=jar,
        stored_at=stored_at,
        workspace_id=payload.get("workspace_id"),
        email=payload.get("email"),
        browser=payload.get("browser"),
    )
