from __future__ import annotations

from collections.abc import Iterable

# weeek_session authenticates, remember_app_* lets it be reissued, the rest are hints.
_KEEP_EXACT = frozenset({"weeek_session", "workspace_id", "user_id", "cid"})
_KEEP_PREFIX = ("remember_app_",)

REQUIRED = "weeek_session"


class CookieError(ValueError):
    pass


def is_session_cookie(name: str) -> bool:
    return name in _KEEP_EXACT or name.startswith(_KEEP_PREFIX)


def select_session_cookies(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {name: value for name, value in pairs if is_session_cookie(name)}


def parse_cookie_header(raw: str) -> dict[str, str]:
    text = raw.strip()
    # DevTools copies come with the header name attached.
    if text[:7].lower() == "cookie:":
        text = text[7:].lstrip()

    jar = select_session_cookies(_split_header(text))
    if REQUIRED not in jar:
        raise CookieError(
            f"No {REQUIRED!r} cookie found in that text. It is HttpOnly, so "
            "document.cookie will not show it. Open DevTools, go to the Network "
            "tab, pick any request to api.weeek.net and copy its whole 'Cookie:' "
            "request header."
        )
    return jar


def _split_header(text: str) -> Iterable[tuple[str, str]]:
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if chunk and "=" in chunk:
            name, _, value = chunk.partition("=")
            yield name.strip(), value.strip()


def to_header(jar: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def redact(jar: dict[str, str]) -> str:
    return ", ".join(sorted(jar)) or "(empty)"
