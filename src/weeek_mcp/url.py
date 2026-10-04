"""Parse whatever gets pasted: a board URL with the task modal open, the
permalink, or a bare id."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

# Anchored on /ws/{ws}/ on purpose: a board URL also contains /project/1/board/1,
# and a looser pattern returns 1 as the task id.
_PATH_TASK = re.compile(r"/ws/(?P<ws>\d+)/(?:task|tm/tasks)/(?P<task>\d+)(?:/|$)")
_PATH_WS = re.compile(r"/ws/(?P<ws>\d+)(?:/|$)")
_BARE_ID = re.compile(r"^#?(?P<task>\d+)$")


class TaskRefError(ValueError):
    pass


@dataclass(frozen=True)
class TaskRef:
    task_id: int
    # Absent for a bare id.
    workspace_id: int | None = None


def parse_task_ref(raw: str) -> TaskRef:
    text = raw.strip()
    if not text:
        raise TaskRefError("Empty input: expected a Weeek task URL or a numeric task id.")

    bare = _BARE_ID.match(text)
    if bare:
        return TaskRef(task_id=int(bare.group("task")))

    url = text if "://" in text else f"https://{text}"
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not (host == "weeek.net" or host.endswith(".weeek.net")):
        raise TaskRefError(
            f"{text!r} is not a Weeek link. Paste a URL from app.weeek.net, "
            "or just the numeric task id."
        )

    query = parse_qs(parts.query)
    task_id = _first_int(query, "m_task_id")
    workspace_id = _first_int(query, "m_task_workspace-id")

    path_match = _PATH_TASK.search(parts.path)
    if task_id is None and path_match:
        task_id = int(path_match.group("task"))

    if task_id is None:
        raise TaskRefError(
            "That Weeek link does not point at a task, it looks like a board, "
            "project or workspace URL. Open the task itself so the address bar "
            "gains an 'm_task_id' parameter, then copy it again."
        )

    if workspace_id is None:
        # The modal parameters win when both are present.
        if path_match:
            workspace_id = int(path_match.group("ws"))
        else:
            ws_match = _PATH_WS.search(parts.path)
            workspace_id = int(ws_match.group("ws")) if ws_match else None

    return TaskRef(task_id=task_id, workspace_id=workspace_id)


def _first_int(query: dict[str, list[str]], key: str) -> int | None:
    for value in query.get(key, []):
        if value.isdigit():
            return int(value)
    return None
