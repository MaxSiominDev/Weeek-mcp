import json
import stat

import pytest

from weeek_mcp.session import storage
from weeek_mcp.session.cookies import CookieError, parse_cookie_header, redact, to_header

# What DevTools puts on the clipboard: the session buried in analytics junk.
PASTED = (
    "Cookie: _ym_uid=1712; weeek_session=s3cret; carrotquest_uid=zz; "
    "remember_app_59ba=r3member; workspace_id=424242; user_id=u-1; cid=c-1"
)


def test_the_header_name_is_stripped_when_the_whole_row_is_pasted():
    jar = parse_cookie_header(PASTED)

    assert jar["weeek_session"] == "s3cret"


@pytest.mark.parametrize("prefix", ["Cookie: ", "cookie:", "COOKIE:  ", ""])
def test_the_prefix_is_optional_and_case_insensitive(prefix):
    assert parse_cookie_header(f"{prefix}weeek_session=abc")["weeek_session"] == "abc"


def test_analytics_cookies_are_discarded():
    jar = parse_cookie_header(PASTED)

    assert set(jar) == {"weeek_session", "remember_app_59ba", "workspace_id", "user_id", "cid"}


def test_remember_me_is_kept_because_it_outlives_the_session():
    assert "remember_app_59ba" in parse_cookie_header(PASTED)


def test_text_without_a_session_cookie_says_where_to_find_it():
    with pytest.raises(CookieError, match="Network"):
        parse_cookie_header("_ym_uid=1712; carrotquest_uid=zz")


def test_values_are_never_included_in_the_redacted_summary():
    summary = redact(parse_cookie_header(PASTED))

    assert "weeek_session" in summary
    assert "s3cret" not in summary
    assert "r3member" not in summary


def test_round_trip_through_the_header_form():
    jar = parse_cookie_header(PASTED)

    assert parse_cookie_header(to_header(jar)) == jar


@pytest.fixture(autouse=True)
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def test_saving_writes_owner_only_permissions():
    path = storage.save(parse_cookie_header(PASTED), workspace_id=424242)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_an_existing_world_readable_file_is_narrowed():
    """os.open's mode only applies on create."""
    path = storage.session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    path.chmod(0o644)

    storage.save(parse_cookie_header(PASTED))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_saved_session_loads_back():
    storage.save(parse_cookie_header(PASTED), workspace_id=424242, email="max@example.com")

    loaded = storage.load()

    assert loaded is not None
    assert loaded.cookies["weeek_session"] == "s3cret"
    assert loaded.workspace_id == 424242
    assert loaded.email == "max@example.com"
    assert loaded.age_hours < 1


def test_a_session_signed_in_with_credentials_can_renew_itself():
    storage.save(parse_cookie_header(PASTED), email="max@example.com")

    assert storage.load().renewable is True


def test_a_pasted_cookie_cannot_renew_itself():
    """No email and no browser means no way back in once the two hours run out."""
    storage.save(parse_cookie_header(PASTED))

    assert storage.load().renewable is False


def test_a_browser_session_round_trips_and_can_renew():
    storage.save(parse_cookie_header(PASTED), workspace_id=424242, browser="chrome")

    loaded = storage.load()

    assert loaded.browser == "chrome"
    assert loaded.email is None
    assert loaded.renewable is True


def test_the_password_is_never_written_to_the_session_file():
    path = storage.save(parse_cookie_header(PASTED), email="max@example.com")

    assert "password" not in path.read_text().lower()


def test_nothing_stored_yet():
    assert storage.load() is None


@pytest.mark.parametrize(
    "content",
    [
        '{"cookie": "_ym_uid=1"}',
        "not json at all",
        '{"stored_at": "2026-01-01T00:00:00+00:00"}',
        '{"cookie": 12345, "stored_at": "2026-01-01T00:00:00+00:00"}',
        "[1, 2, 3]",
        "null",
    ],
)
def test_a_corrupt_session_file_is_treated_as_absent(content):
    path = storage.session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

    assert storage.load() is None


def test_the_stored_file_records_when_it_was_captured():
    """Weeek issues these with Max-Age=7200, so the age decides whether to renew."""
    payload = json.loads(storage.save(parse_cookie_header(PASTED)).read_text())

    assert "stored_at" in payload
