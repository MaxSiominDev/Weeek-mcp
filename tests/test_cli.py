import weeek_mcp.__main__ as cli
from weeek_mcp.config import Config
from weeek_mcp.errors import SessionExpired
from weeek_mcp.session import browser, credentials, storage
from weeek_mcp.session.storage import StoredSession


class FakeSession:
    def __init__(self, *_a, error=None):
        self._error = error

    def __call__(self, *_a):  # constructed as SessionApi(cookies, client)
        return self

    async def workspaces(self):
        if self._error:
            raise self._error
        return [{"id": 1}]


def stored(**kw) -> StoredSession:
    from datetime import UTC, datetime

    kw.setdefault("cookies", {"weeek_session": "s"})
    kw.setdefault("stored_at", datetime.now(UTC))
    return StoredSession(**kw)


def wire(monkeypatch, *, session, session_api=None):
    monkeypatch.setattr(cli.config, "load", lambda: Config(session=session))
    monkeypatch.setattr(cli, "SessionApi", session_api or FakeSession())


async def test_doctor_reports_a_browser_session_that_can_self_renew(monkeypatch, capsys):
    wire(monkeypatch, session=stored(browser="chrome", workspace_id=1))
    monkeypatch.setattr(browser, "library_installed", lambda: True)

    rc = await cli._doctor()
    out = capsys.readouterr().out

    assert rc == 0
    assert "read from chrome" in out
    assert "session accepted by Weeek right now" in out


async def test_doctor_warns_when_the_browser_library_is_absent(monkeypatch, capsys):
    wire(monkeypatch, session=stored(browser="chrome"))
    monkeypatch.setattr(browser, "library_installed", lambda: False)

    rc = await cli._doctor()
    out = capsys.readouterr().out

    assert rc == 0
    assert "[warn] read from chrome" in out
    assert "[browser] extra" in out


async def test_doctor_fails_when_the_password_is_gone(monkeypatch, capsys):
    wire(monkeypatch, session=stored(email="max@example.com"))
    monkeypatch.setattr(credentials, "password_for", lambda email: None)

    rc = await cli._doctor()
    out = capsys.readouterr().out

    assert rc == 1
    assert "no password in the keychain" in out


async def test_doctor_warns_when_a_renewable_session_has_expired(monkeypatch, capsys):
    wire(
        monkeypatch,
        session=stored(email="max@example.com"),
        session_api=FakeSession(error=SessionExpired()),
    )
    monkeypatch.setattr(credentials, "password_for", lambda email: "s3cret")

    rc = await cli._doctor()
    out = capsys.readouterr().out

    assert rc == 0  # expired but renewable is only a warning
    assert "will renew on next use" in out


async def test_doctor_fails_when_a_stuck_session_has_no_way_back(monkeypatch, capsys):
    """A pasted cookie with no remember-me and no renewal path: expired means done."""
    wire(
        monkeypatch,
        session=stored(),
        session_api=FakeSession(error=SessionExpired()),
    )

    rc = await cli._doctor()
    out = capsys.readouterr().out

    assert rc == 1
    assert "[FAIL] session" in out


async def test_doctor_fails_with_no_session_stored(monkeypatch, capsys):
    wire(monkeypatch, session=None)

    rc = await cli._doctor()
    out = capsys.readouterr().out

    assert rc == 1
    assert "Weeek sign-in: none stored" in out


def test_logout_removes_the_session_and_password(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    forgotten = []
    monkeypatch.setattr(credentials, "forget", lambda email: forgotten.append(email))
    storage.save({"weeek_session": "s"}, email="max@example.com")

    rc = cli._logout()
    out = capsys.readouterr().err

    assert rc == 0
    assert not storage.session_path().exists()
    assert forgotten == ["max@example.com"]
    assert "stored password" in out


def test_logout_is_quiet_about_a_password_it_never_had(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    storage.save({"weeek_session": "s"}, browser="chrome")

    rc = cli._logout()
    out = capsys.readouterr().err

    assert rc == 0
    assert "stored password" not in out
