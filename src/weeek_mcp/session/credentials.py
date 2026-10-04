"""The password lives in the OS keychain, never in a file."""

from __future__ import annotations

import contextlib
import logging

log = logging.getLogger(__name__)

SERVICE = "weeek-mcp"


class KeychainUnavailable(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            f"No usable keychain on this system ({detail}). Sign in with "
            "`weeek-mcp login --cookie` instead, which stores no password."
        )


def save(email: str, password: str) -> None:
    _keyring().set_password(SERVICE, email, password)


def password_for(email: str) -> str | None:
    try:
        return _keyring().get_password(SERVICE, email)
    except Exception as exc:  # noqa: BLE001  a locked keychain must not crash a read
        log.warning("keychain lookup failed: %s", type(exc).__name__)
        return None


def forget(email: str) -> None:
    # Deleting what was never stored is not an error.
    with contextlib.suppress(Exception):
        _keyring().delete_password(SERVICE, email)


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
    except ImportError as exc:
        raise KeychainUnavailable(str(exc)) from None

    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring):
        raise KeychainUnavailable("keyring found no backend")
    return keyring
