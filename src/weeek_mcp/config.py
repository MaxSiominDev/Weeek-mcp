from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from .session import storage
from .session.cookies import CookieError, parse_cookie_header
from .session.storage import StoredSession

COOKIE_ENV = "WEEEK_COOKIE"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    session: StoredSession | None

    def require_session(self) -> StoredSession:
        if self.session is None:
            raise ConfigError(
                "No Weeek browser session stored, and nothing can be read without "
                "one (Weeek only serves tasks to a signed-in session).\n"
                "Run `weeek-mcp login --from-browser`, or `weeek-mcp login --cookie` "
                "and paste the 'Cookie:' request header of any api.weeek.net request "
                "from your browser's DevTools Network tab."
            )
        return self.session


def load() -> Config:
    # A WEEEK_COOKIE override wins over the stored session and is never persisted.
    raw = os.environ.get(COOKIE_ENV, "").strip()
    if raw:
        try:
            cookies = parse_cookie_header(raw)
        except CookieError as exc:
            raise ConfigError(f"{COOKIE_ENV} is set but unusable. {exc}") from None
        session = StoredSession(cookies=cookies, stored_at=datetime.now(UTC), ephemeral=True)
        return Config(session=session)

    return Config(session=storage.load())
