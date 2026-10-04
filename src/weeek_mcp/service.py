"""Assemble one task: the body, its comments, and every file it mentions."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import replace

import httpx2

from .config import Config
from .errors import SessionExpired, WeeekError
from .files import store
from .files.download import fetch_attachments, fetch_comment_images
from .render.task import Names, render
from .session import auth, browser, credentials, storage
from .session.client import SessionApi
from .session.prosemirror import ImageRef, body_of, collect_images
from .session.storage import StoredSession
from .url import TaskRef, parse_task_ref

TIMEOUT = 30.0


async def get_task(
    raw_url: str, config: Config, *, client: httpx2.AsyncClient | None = None
) -> str:
    ref = parse_task_ref(raw_url)
    session = config.require_session()
    warnings: list[str] = []

    store.sweep()

    async with AsyncExitStack() as stack:
        if client is None:
            client = await stack.enter_async_context(
                httpx2.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
            )
        private = SessionApi(session.cookies, client)

        try:
            task, names, files, workspace_id = await _read(private, ref, session)
        except SessionExpired:
            fresh = await _renew(session, client)
            private = SessionApi(fresh, client)
            try:
                task, names, files, workspace_id = await _read(private, ref, session)
            except SessionExpired:
                raise _renewal_failed(session) from None
            # Persist only once the fresh jar has proven itself.
            storage.save(
                fresh,
                workspace_id=workspace_id,
                email=session.email,
                browser=session.browser,
            )
            session = replace(session, cookies=fresh)

        comments = [c for c in task.get("comments") or [] if isinstance(c, dict)]

        expected = task.get("commentsCount")
        if isinstance(expected, int) and expected != len(comments):
            warnings.append(
                f"Weeek reports {expected} comments but returned {len(comments)}. "
                "Some may be missing from this response."
            )

        directory = store.task_dir(ref.task_id)
        images: list[ImageRef] = collect_images([body_of(task)])
        images += collect_images([body_of(c) for c in comments])
        attachments, comment_images = await asyncio.gather(
            fetch_attachments(private, files, directory),
            fetch_comment_images(private, images, directory),
        )

        # Keep a mid-request reissue, unless the session came from WEEEK_COOKIE.
        if private.refreshed and not session.ephemeral:
            storage.save(
                private.cookies,
                workspace_id=workspace_id,
                email=session.email,
                browser=session.browser,
            )

    return render(
        task,
        url=_permalink(workspace_id, ref.task_id),
        names=names,
        comments=comments,
        attachments=attachments,
        comment_images=comment_images,
        warnings=warnings,
    )


async def _read(
    private: SessionApi, ref: TaskRef, session: StoredSession
) -> tuple[dict, Names, list[dict], int]:
    workspace_id = await _workspace_id(ref.workspace_id or session.workspace_id, private)
    # return_exceptions: all three settle even when one fails.
    task, names, files = _first_error_or(
        await asyncio.gather(
            private.task_with_comments(workspace_id, ref.task_id),
            _lookups(private, workspace_id),
            private.task_files(workspace_id, ref.task_id),
            return_exceptions=True,
        )
    )
    return task, names, files, workspace_id


def _first_error_or(results: list):
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


async def _lookups(private: SessionApi, workspace_id: int) -> Names:
    # Cosmetic: raw ids beat failing the whole read.
    members, projects = await asyncio.gather(
        private.members(workspace_id), private.projects(workspace_id), return_exceptions=True
    )
    names = Names()
    if isinstance(members, list):
        for member in members:
            if isinstance(member, dict) and member.get("id"):
                label = " ".join(
                    filter(None, [member.get("firstName"), member.get("lastName")])
                ).strip()
                names.people[str(member["id"])] = label or str(member.get("email") or member["id"])
    if isinstance(projects, list):
        for project in projects:
            if isinstance(project, dict) and project.get("id") is not None:
                names.projects[int(project["id"])] = str(project.get("name") or project["id"])
    return names


async def _workspace_id(known: int | None, private: SessionApi) -> int:
    if known:
        return known
    workspaces = await private.workspaces()
    if workspaces:
        try:
            return int(workspaces[0]["id"])
        except (KeyError, TypeError, ValueError):
            pass
    raise WeeekError(
        "Could not determine which workspace this task belongs to. Paste the "
        "full task link from the browser, it carries the workspace id, "
        "rather than a bare task number."
    )


async def _renew(session: StoredSession, client: httpx2.AsyncClient) -> dict[str, str]:
    if session.email is not None:
        return await _renew_by_password(session, client)
    if session.browser is not None:
        # Keychain and file reads can block on a dialog.
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(browser.extract, session.browser), timeout=30
            )
        except TimeoutError:
            raise WeeekError(
                f"Reading the Weeek session from {session.browser} timed out, a "
                "keychain prompt may be waiting for you. Approve it (choose "
                "'Always Allow'), or run `weeek-mcp login --from-browser` in a terminal."
            ) from None
    raise SessionExpired() from None


async def _renew_by_password(session: StoredSession, client: httpx2.AsyncClient) -> dict[str, str]:
    password = credentials.password_for(session.email or "")
    if not password:
        raise WeeekError(
            f"The Weeek session has expired and no password is stored for "
            f"{session.email} to renew it with. Run `weeek-mcp login` again."
        )
    return await auth.login(session.email or "", password, client)


def _renewal_failed(session: StoredSession) -> WeeekError:
    if session.browser:
        return WeeekError(
            f"The Weeek session has expired and the cookie in {session.browser} is "
            f"no longer valid either. Open app.weeek.net in {session.browser}, log "
            "in, then try again."
        )
    return SessionExpired()


def _permalink(workspace_id: int, task_id: int) -> str:
    return f"https://app.weeek.net/ws/{workspace_id}/task/{task_id}"
