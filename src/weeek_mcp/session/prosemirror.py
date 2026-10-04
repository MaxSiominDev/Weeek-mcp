"""Render Weeek's ProseMirror bodies as Markdown.

Ported from the read half of adalekin/weeek-mcp (MIT, see NOTICE). Weeek's
dialect diverges from stock TipTap where it matters: lists are flat sibling
`list` nodes with a `kind` attribute, soft breaks are `line-break`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

_MARK_WRAP = {
    "bold": "**",
    "italic": "*",
    "strike": "~~",
    "strikethrough": "~~",
    "code": "`",
    "inline-code": "`",
}


class ImageRef(NamedTuple):
    link: str
    name: str | None = None
    size: int | None = None


def body_of(comment: dict) -> Any:
    # Bodies arrive wrapped as {"data": doc}, sometimes bare.
    content = comment.get("content")
    if isinstance(content, dict) and "data" in content:
        return content["data"]
    return content


def collect_images(doc: Any) -> list[ImageRef]:
    found: list[ImageRef] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "image":
                attrs = node.get("attrs") or {}
                link = attrs.get("link") or attrs.get("src")
                if link:
                    found.append(ImageRef(link, attrs.get("name"), attrs.get("size")))
            # Descend through every value, not just "content".
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return found


def to_markdown(doc: Any, image_text: Callable[[ImageRef], str] | None = None) -> str:
    # image_text lets the caller swap an image for its downloaded local path.
    return _Renderer(image_text or _default_image).render(doc)


def _default_image(image: ImageRef) -> str:
    return f"![{image.name or ''}]({image.link})"


class _Renderer:
    def __init__(self, image_text: Callable[[ImageRef], str]) -> None:
        self._image_text = image_text

    def render(self, doc: Any) -> str:
        if isinstance(doc, dict):
            nodes = doc.get("content") or []
        elif isinstance(doc, list):
            nodes = doc
        else:
            return ""
        return self._blocks(nodes).strip()

    def _image(self, node: dict) -> str:
        attrs = node.get("attrs") or {}
        link = attrs.get("link") or attrs.get("src") or ""
        return self._image_text(ImageRef(link, attrs.get("name"), attrs.get("size")))

    def _inline(self, nodes: Any) -> str:
        out: list[str] = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            kind = node.get("type")
            if kind == "text":
                out.append(self._marked(node))
            elif kind == "line-break":
                out.append("  \n")
            elif kind == "image":
                out.append(self._image(node))
            else:
                out.append(self._inline(node.get("content")))
        return "".join(out)

    @staticmethod
    def _marked(node: dict) -> str:
        text = node.get("text", "")
        for mark in node.get("marks") or []:
            mark_type = mark.get("type")
            if mark_type == "link":
                attrs = mark.get("attrs") or {}
                text = f"[{text}]({attrs.get('href') or attrs.get('link') or ''})"
            elif mark_type in _MARK_WRAP:
                wrap = _MARK_WRAP[mark_type]
                text = f"{wrap}{text}{wrap}"
        return text

    def _plain(self, nodes: Any) -> str:
        out: list[str] = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "text":
                out.append(node.get("text", ""))
            elif node.get("type") == "line-break":
                out.append("\n")
            else:
                out.append(self._plain(node.get("content")))
        return "".join(out)

    def _blocks(self, nodes: Any) -> str:
        blocks: list[str] = []
        pending_list: list[str] = []

        def flush() -> None:
            if pending_list:
                blocks.append("\n".join(pending_list))
                pending_list.clear()

        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            # Consecutive list nodes are siblings, not children.
            if node.get("type") == "list":
                pending_list.append(self._list_item(node, 0))
                continue
            flush()
            rendered = self._block(node)
            if rendered.strip():
                blocks.append(rendered)
        flush()
        return "\n\n".join(blocks)

    def _block(self, node: dict) -> str:
        kind = node.get("type")
        attrs = node.get("attrs") or {}
        content = node.get("content") or []

        if kind == "heading":
            level = max(1, min(6, int(attrs.get("level") or 1)))
            return "#" * level + " " + self._inline(content)
        if kind == "paragraph":
            return self._inline(content)
        if kind == "quote":
            inner = self._blocks(content)
            return "\n".join(("> " + line).rstrip() for line in inner.splitlines() or [""])
        if kind == "code":
            language = attrs.get("language") or attrs.get("lang") or ""
            return f"```{language}\n{self._plain(content)}\n```"
        if kind == "horizontal-line":
            return "---"
        if kind == "image":
            return self._image(node)
        if kind == "list":
            return self._list_item(node, 0)
        if kind in ("table", "table_body", "table_row", "table_cell"):
            return self._table(node)
        if kind == "table_html":
            return self._plain(content)
        # An unknown wrapper must not swallow its text.
        return self._blocks(content)

    def _list_item(self, node: dict, depth: int) -> str:
        attrs = node.get("attrs") or {}
        kind = attrs.get("kind", "bullet")
        if kind in ("check", "todo", "checkbox"):
            marker = "- [x] " if attrs.get("checked") else "- [ ] "
        elif kind in ("number", "ordered"):
            marker = "1. "
        else:
            marker = "- "

        text: list[str] = []
        nested: list[str] = []
        for child in node.get("content") or []:
            if not isinstance(child, dict):
                continue
            if child.get("type") == "list":
                nested.append(self._list_item(child, depth + 1))
            elif child.get("type") == "paragraph":
                text.append(self._inline(child.get("content")))
            else:
                text.append(self._block(child))

        line = "  " * depth + marker + " ".join(p for p in text if p.strip()).strip()
        return line + "\n" + "\n".join(nested) if nested else line

    def _table(self, node: dict) -> str:
        rows: list[dict] = []

        def find_rows(current: dict) -> None:
            for child in current.get("content") or []:
                if not isinstance(child, dict):
                    continue
                if child.get("type") == "table_row":
                    rows.append(child)
                else:
                    find_rows(child)

        find_rows(node)
        if not rows:
            return ""

        lines: list[str] = []
        for index, row in enumerate(rows):
            cells = [
                self._cell(cell)
                for cell in (row.get("content") or [])
                if isinstance(cell, dict) and cell.get("type") == "table_cell"
            ]
            lines.append("| " + " | ".join(cells) + " |")
            if index == 0:
                lines.append("| " + " | ".join("---" for _ in cells) + " |")
        return "\n".join(lines)

    def _cell(self, cell: dict) -> str:
        text = self._blocks(cell.get("content") or [])
        return text.replace("\n", " ").replace("|", "\\|").strip()
