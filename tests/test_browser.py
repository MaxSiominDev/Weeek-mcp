import sys
import types

import pytest

from weeek_mcp.session import browser
from weeek_mcp.session.browser import SUPPORTED, BrowserUnavailable, extract, library_installed

# A browser store holds far more than the session; only the relevant pairs are kept.
FULL_JAR = [
    ("weeek_session", "live"),
    ("remember_app_59ba", "rememberme"),
    ("workspace_id", "424242"),
    ("_ym_uid", "analytics"),
    ("cf_clearance", "cloudflare"),
]


def reader_returning(pairs):
    def read(domain):
        assert domain == "weeek.net"
        return pairs

    return read


def test_only_session_cookies_are_taken_from_the_browser():
    jar = extract("chrome", reader=reader_returning(FULL_JAR))

    assert jar == {
        "weeek_session": "live",
        "remember_app_59ba": "rememberme",
        "workspace_id": "424242",
    }


def test_an_unsupported_browser_lists_the_supported_ones():
    with pytest.raises(BrowserUnavailable, match="chrome"):
        extract("netscape", reader=reader_returning(FULL_JAR))


def test_no_weeek_login_in_the_browser_is_explained():
    with pytest.raises(BrowserUnavailable, match="log in"):
        extract("chrome", reader=reader_returning([("_ym_uid", "x")]))


def test_a_read_failure_adds_the_keychain_and_close_the_browser_hint():
    # An exception whose own text shares no words with the hint, so the assertion
    # can only pass if _read_failure actually contributes the advice.
    def failing(_domain):
        raise RuntimeError("database is busy")

    with pytest.raises(BrowserUnavailable, match=r"keychain prompt|closing it"):
        extract("chrome", reader=failing)


def test_the_real_reader_passes_the_domain_and_returns_name_value_pairs(monkeypatch):
    """Covers the real browser_cookie3 wiring, which the injected reader skips."""
    seen = {}

    def fake_chrome(domain_name=""):
        seen["domain"] = domain_name
        cookie = types.SimpleNamespace(name="weeek_session", value="live")
        return [cookie]

    fake_module = types.SimpleNamespace(chrome=fake_chrome)
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_module)

    jar = extract("chrome")

    assert seen["domain"] == "weeek.net"
    assert jar == {"weeek_session": "live"}


def test_every_supported_browser_exists_in_the_library():
    """A name dropped upstream should fail here, not at runtime."""
    import browser_cookie3 as bc

    for name in SUPPORTED:
        assert hasattr(bc, name), name


def test_library_installed_reports_the_truth():
    assert library_installed() is True  # browser_cookie3 is a dev dependency


def test_library_installed_is_false_without_the_library(monkeypatch):
    monkeypatch.setitem(sys.modules, "browser_cookie3", None)  # forces ImportError
    assert browser.library_installed() is False


def test_a_missing_library_tells_you_how_to_install_it(monkeypatch):
    # Simulate browser_cookie3 not being installed by forcing the import to fail.
    import builtins

    real_import = builtins.__import__

    def no_bc(name, *args, **kwargs):
        if name == "browser_cookie3":
            raise ImportError("No module named 'browser_cookie3'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_bc)

    with pytest.raises(BrowserUnavailable, match="weeek-mcp\\[browser\\]"):
        extract("chrome")
