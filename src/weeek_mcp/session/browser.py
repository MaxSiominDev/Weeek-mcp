"""Read the Weeek session from a logged-in browser's cookie store.

The cookie is HttpOnly, so a page cannot see it, but the browser keeps it in
its own database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..errors import WeeekError
from .cookies import REQUIRED, select_session_cookies

# Safari needs Full Disk Access to read; not worth it.
SUPPORTED = ("chrome", "arc", "brave", "edge", "chromium", "vivaldi", "opera", "firefox")

Reader = Callable[[str], Iterable[tuple[str, str]]]


class BrowserUnavailable(WeeekError):
    pass


def library_installed() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("browser_cookie3") is not None
    except (ImportError, ValueError):
        return False


def extract(browser: str, reader: Reader | None = None) -> dict[str, str]:
    if browser not in SUPPORTED:
        raise BrowserUnavailable(
            f"{browser!r} is not a supported browser. Choose one of: "
            f"{', '.join(SUPPORTED)}."
        )

    read = reader or _default_reader(browser)
    try:
        pairs = list(read("weeek.net"))
    except Exception as exc:
        raise BrowserUnavailable(_read_failure(browser, exc)) from exc

    jar = select_session_cookies(pairs)
    if REQUIRED not in jar:
        raise BrowserUnavailable(
            f"No Weeek session found in {browser}. Open app.weeek.net in it and log "
            "in, then run this again."
        )
    return jar


def _default_reader(browser: str) -> Reader:
    try:
        import browser_cookie3 as bc
    except ImportError:
        raise BrowserUnavailable(
            "Reading cookies from the browser needs an extra library. Install it "
            "with:  pip install 'weeek-mcp[browser]'  (or: uvx --from "
            "'weeek-mcp[browser]' weeek-mcp login --from-browser)."
        ) from None

    loader = getattr(bc, browser, None)
    if loader is None:  # pragma: no cover - guarded by SUPPORTED
        raise BrowserUnavailable(f"{browser!r} is not supported by the cookie reader.")

    def read(domain: str) -> Iterable[tuple[str, str]]:
        jar = loader(domain_name=domain)
        return [(cookie.name, cookie.value) for cookie in jar]

    return read


def _read_failure(browser: str, exc: Exception) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    hint = ""
    if browser in ("chrome", "arc", "brave", "edge", "chromium", "vivaldi", "opera"):
        hint = (
            " If a keychain prompt appeared, allow it and run this again. An open "
            "browser can lock its cookie database, so try closing it."
        )
    return f"Could not read cookies from {browser}: {detail}.{hint}"
