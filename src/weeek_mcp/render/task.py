"""Lay a task out as Markdown for a model to read."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..files.download import Downloaded
from ..session.prosemirror import ImageRef, body_of, to_markdown

PRIORITIES = {0: "Low", 1: "Medium", 2: "High", 3: "Hold"}


@dataclass
class Names:
    people: dict[str, str] = field(default_factory=dict)
    projects: dict[int, str] = field(default_factory=dict)

    def person(self, uuid: Any) -> str:
        return self.people.get(str(uuid), str(uuid))

    def project(self, project_id: Any) -> str | None:
        try:
            return self.projects.get(int(project_id))
        except (TypeError, ValueError):
            return None


def render(
    task: dict,
    *,
    url: str,
    names: Names,
    comments: list[dict],
    attachments: list[Downloaded],
    comment_images: dict[str, Downloaded],
    warnings: list[str] | None = None,
) -> str:
    parts = [_header(task, url, names), _description(task, comment_images)]

    if attachments:
        parts.append(_attachments(attachments))
    parts.append(_comments(comments, names, comment_images))

    if warnings:
        parts.append("## Warnings\n" + "\n".join(f"- {w}" for w in warnings))

    return "\n\n".join(part for part in parts if part)


def _header(task: dict, url: str, names: Names) -> str:
    title = task.get("title") or "(untitled)"
    lines = [f"# {title}", ""]

    facts: list[str] = [f"Task {task.get('id')}", url]
    lines.append(" · ".join(facts))

    state = "completed" if _truthy(task.get("completed")) else "open"
    detail = [f"**Status:** {state}"]
    priority = PRIORITIES.get(task.get("priority"))
    if priority:
        detail.append(f"**Priority:** {priority}")
    if task.get("type") and task["type"] != "action":
        detail.append(f"**Type:** {task['type']}")
    lines.append(" · ".join(detail))

    for location in task.get("locations") or []:
        if not isinstance(location, dict):
            continue
        project = names.project(location.get("projectId"))
        if project:
            lines.append(f"**Project:** {project}")

    assignees = [names.person(a) for a in task.get("assignees") or []]
    if assignees:
        lines.append(f"**Assignees:** {', '.join(assignees)}")
    if task.get("authorId"):
        lines.append(f"**Author:** {names.person(task['authorId'])}")

    dates = []
    if task.get("startDateTime"):
        dates.append(f"starts {_date(task['startDateTime'])}")
    if task.get("dueDateTime"):
        dates.append(f"due {_date(task['dueDateTime'])}")
    if task.get("createdAt"):
        dates.append(f"created {_date(task['createdAt'])}")
    if dates:
        lines.append(f"**Dates:** {', '.join(dates)}")

    return "\n".join(lines)


def _description(task: dict, images: dict[str, Downloaded]) -> str:
    # The body is the same ProseMirror dialect comments use, images included.
    body = to_markdown(body_of(task), image_text=lambda ref: _image_line(ref, images))
    return f"## Description\n\n{body}" if body else "## Description\n\n_(empty)_"


def _attachments(attachments: list[Downloaded]) -> str:
    lines = ["## Attachments", ""]
    viewable = [a for a in attachments if a.viewable]
    if viewable:
        lines.append(
            f"{len(viewable)} image(s) were downloaded. **Open them with the Read tool** "
            "to see what they show; they are not included in this response."
        )
        lines.append("")

    for item in attachments:
        if item.path:
            marker = "image" if item.viewable else (item.mime or "file")
            note = "" if item.viewable else f", {item.skipped}"
            lines.append(f"- `{item.path}` ({item.name}, {marker}, {_size(item.size)}){note}")
        else:
            # A Weeek URL is a credential; only external links are shown.
            where = f" <{item.url}>" if item.url and item.external else ""
            lines.append(f"- {item.name}: not downloaded, {item.skipped}{where}")
    return "\n".join(lines)


def _comments(comments: list[dict], names: Names, images: dict[str, Downloaded]) -> str:
    if not comments:
        return "## Comments\n\n_(none)_"

    lines = [f"## Comments ({len(comments)})", ""]
    # An id-less comment must not key None.
    by_id = {c["id"]: c for c in comments if isinstance(c, dict) and c.get("id") is not None}

    for comment in comments:
        if not isinstance(comment, dict):
            continue
        lines.append(_comment(comment, by_id, names, images))
    return "\n".join(lines)


def _comment(
    comment: dict, by_id: dict, names: Names, images: dict[str, Downloaded]
) -> str:
    author = _author(comment, names)
    when = _date(comment.get("sentAt") or "")
    edited = " (edited)" if comment.get("isUpdated") else ""

    head = f"### {author}, {when}{edited}"
    parent_id = comment.get("parentId")
    parent = by_id.get(parent_id) if parent_id is not None else None
    if parent is not None:
        head += f"\n_in reply to {_author(parent, names)}_"

    body = to_markdown(body_of(comment), image_text=lambda ref: _image_line(ref, images))
    return f"{head}\n\n{body or '_(empty)_'}\n"


def _image_line(ref: ImageRef, images: dict[str, Downloaded]) -> str:
    downloaded = images.get(ref.link)
    label = ref.name or "image"
    if downloaded is None:
        return f"[{label}: not downloaded]"
    # Viewable, not merely on disk: an SVG or a PDF must not be offered as an image.
    if not downloaded.viewable:
        where = f" (saved to `{downloaded.path}`)" if downloaded.path else ""
        return f"[{label}: unavailable, {downloaded.skipped}{where}]"
    return f"[{label}: open `{downloaded.path}` with Read]"


def _author(comment: dict, names: Names) -> str:
    user = comment.get("user") or {}
    name = user.get("name") or " ".join(
        filter(None, [user.get("first_name"), user.get("last_name")])
    ).strip()
    if name:
        return name
    return names.person(comment.get("userId"))


def _truthy(value: Any) -> bool:
    # Weeek mixes 0/1 and true/false, sometimes in one object.
    return value in (True, 1, "1")


def _date(value: str) -> str:
    text = value.replace("T", " ").replace("Z", "").strip()
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")].strip()
    return text or "unknown date"


def _size(count: int) -> str:
    if count >= 1_048_576:
        return f"{count / 1_048_576:.1f} MB"
    if count >= 1024:
        return f"{count / 1024:.0f} KB"
    return f"{count} B"
