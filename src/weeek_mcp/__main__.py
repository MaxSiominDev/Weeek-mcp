"""Command line: run the server, sign in, or diagnose a broken setup."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys

import httpx2

from . import config
from .errors import WeeekError
from .session import auth, browser, credentials, storage
from .session.client import SessionApi
from .session.cookies import CookieError, parse_cookie_header, redact


def main() -> int:
    parser = argparse.ArgumentParser(prog="weeek-mcp", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    login = sub.add_parser("login", help="sign in to Weeek so comments can be read")
    mode = login.add_mutually_exclusive_group()
    mode.add_argument(
        "--from-browser",
        metavar="BROWSER",
        nargs="?",
        const="chrome",
        help="read the session from a logged-in browser (default: chrome). Best "
        "for Google/SSO accounts: no password, no DevTools, and it renews itself",
    )
    mode.add_argument(
        "--cookie",
        action="store_true",
        help="paste a browser cookie by hand instead",
    )
    sub.add_parser("doctor", help="check the stored session and explain any failure")
    sub.add_parser("logout", help="forget the stored session and password")
    args = parser.parse_args()

    # stdout carries the JSON-RPC stream.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    # httpx request lines would put signed attachment URLs into the host log.
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    if args.command == "login":
        if args.from_browser is not None:
            return asyncio.run(_login_from_browser(args.from_browser or "chrome"))
        if args.cookie:
            return asyncio.run(_login_with_cookie())
        return asyncio.run(_login_with_password())
    if args.command == "doctor":
        return asyncio.run(_doctor())
    if args.command == "logout":
        return _logout()

    from .server import build

    build().run()
    return 0


async def _login_with_password() -> int:
    print(
        "Sign in to Weeek. The password goes into your system keychain, never into "
        "a file.\nIt is needed because a Weeek session lasts only about two hours, "
        "so storing it\nlets the server sign in again on its own.\n",
        file=sys.stderr,
    )
    try:
        email = input("Email: ").strip()
        password = getpass.getpass("Password: ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 2
    if not email or not password:
        print("Both an email and a password are required.", file=sys.stderr)
        return 2

    async with httpx2.AsyncClient(timeout=30) as client:
        try:
            jar = await auth.login(email, password, client)
        except WeeekError as exc:
            print(f"\nSign-in failed: {exc}", file=sys.stderr)
            return 1
        workspace_id = await _discover_workspace(jar, client)

    try:
        credentials.save(email, password)
    except credentials.KeychainUnavailable as exc:
        print(f"\nSigned in, but the password could not be stored: {exc}", file=sys.stderr)
        return 1

    path = storage.save(jar, workspace_id=workspace_id, email=email)
    print(
        f"\nSigned in as {email}"
        + (f" (workspace {workspace_id})" if workspace_id else "")
        + f".\nSession stored in {path} (mode 0600); password in the keychain."
        "\nThe server renews the session by itself from now on.",
        file=sys.stderr,
    )
    return 0


async def _login_from_browser(which: str) -> int:
    print(
        f"Reading your Weeek session from {which}.\n"
        "A one-time keychain prompt may appear, the OS asking you to allow it. "
        "Choose 'Always Allow' so the server can refresh the session later "
        "without prompting again.\n",
        file=sys.stderr,
    )
    try:
        jar = await asyncio.to_thread(browser.extract, which)
    except WeeekError as exc:
        print(f"Could not read the session: {exc}", file=sys.stderr)
        return 1

    async with httpx2.AsyncClient(timeout=30) as client:
        try:
            workspace_id = await _discover_workspace(jar, client, strict=True)
        except WeeekError as exc:
            print(
                f"Read a cookie from {which}, but Weeek rejected it: {exc}\n"
                "Make sure you are logged in to app.weeek.net in that browser.",
                file=sys.stderr,
            )
            return 1

    path = storage.save(jar, workspace_id=workspace_id, browser=which)
    detail = redact(jar)
    renews = (
        "The server refreshes it as you work, and re-reads it from the browser if it "
        "ever fully lapses, so this should be the only time you run this."
        if browser.library_installed()
        else "Install the server with the [browser] extra (see the README) so it can "
        "re-read the browser when the session lapses; otherwise re-run this then."
    )
    print(
        f"Read the session from {which}"
        + (f" (workspace {workspace_id})" if workspace_id else "")
        + f" and stored {detail} in {path}.\n{renews}",
        file=sys.stderr,
    )
    return 0


async def _login_with_cookie() -> int:
    print(
        "Paste the whole 'Cookie:' request header from your browser.\n"
        "  1. open app.weeek.net and log in\n"
        "  2. DevTools -> Network, click anything so requests appear\n"
        "  3. pick any request to api.weeek.net, copy its Cookie request header\n"
        "Use the Network tab, not the console: weeek_session is HttpOnly.\n\n"
        "Copy the ENTIRE line. Weeek's session lasts about two hours, but the\n"
        "remember_app_* cookie next to it is what lets Weeek reissue the session\n"
        "silently: with it this is a one-time step, without it a two-hourly one.\n",
        file=sys.stderr,
    )
    raw = sys.stdin.readline()
    if not raw.strip():
        print("Nothing pasted.", file=sys.stderr)
        return 2

    try:
        jar = parse_cookie_header(raw)
    except CookieError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    async with httpx2.AsyncClient(timeout=30) as client:
        try:
            workspace_id = await _discover_workspace(jar, client, strict=True)
        except WeeekError as exc:
            print(f"That cookie does not work: {exc}", file=sys.stderr)
            return 1

    path = storage.save(jar, workspace_id=workspace_id)
    print(f"Stored {redact(jar)} in {path} (mode 0600).", file=sys.stderr)
    return 0


async def _discover_workspace(
    jar: dict[str, str], client: httpx2.AsyncClient, strict: bool = False
) -> int | None:
    try:
        workspaces = await SessionApi(jar, client).workspaces()
    except WeeekError:
        if strict:
            raise
        return None
    return workspaces[0].get("id") if workspaces else None


async def _doctor() -> int:
    ok = True
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 1

    async with httpx2.AsyncClient(timeout=30) as client:
        if cfg.session is None:
            print("[FAIL] Weeek sign-in: none stored. Run `weeek-mcp login --from-browser`.")
            print("       Nothing can be read without it, and this server requires it.")
            return 1

        session = cfg.session
        print(f"[ok]   session cookies present: {redact(session.cookies)}")
        print(f"       captured {session.age_hours:.1f} h ago (Weeek expires these after ~2 h)")

        has_remember = any(name.startswith("remember_app_") for name in session.cookies)
        if session.browser:
            if browser.library_installed():
                print(f"[ok]   read from {session.browser}, re-read from there if it lapses")
            else:
                print(f"[warn] read from {session.browser}, but the browser-reading library")
                print("       is not installed in this environment, so it cannot re-read")
                print("       automatically. Install the server with the [browser] extra")
                print("       (see the README), or it stops working when the session lapses.")
        elif session.email:
            if credentials.password_for(session.email or ""):
                print(f"[ok]   renews itself by signing in again as {session.email}")
            else:
                print(f"[FAIL] {session.email} has no password in the keychain to renew with.")
                print("       Run `weeek-mcp login` again.")
                ok = False
        elif has_remember:
            print("[ok]   carries a remember_app_* cookie, Weeek should reissue the session")
            print("       on its own, and the replacement is saved automatically")
        else:
            print("[warn] no remember_app_* cookie alongside the session, so it cannot renew.")
            print("       It will stop working in about two hours. Re-run")
            print("       `weeek-mcp login --cookie` and copy the WHOLE Cookie line.")

        try:
            await SessionApi(session.cookies, client).workspaces()
            print("[ok]   session accepted by Weeek right now")
        except WeeekError as exc:
            if session.renewable:
                print(f"[warn] session expired ({exc.__class__.__name__}); will renew on next use")
            else:
                print(f"[FAIL] session: {exc}")
                ok = False

    return 0 if ok else 1


def _logout() -> int:
    session = storage.load()
    forgot_password = bool(session and session.email)
    if forgot_password:
        credentials.forget(session.email)
    path = storage.session_path()
    path.unlink(missing_ok=True)
    tail = " and the stored password" if forgot_password else ""
    print(f"Forgot the session in {path}{tail}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
