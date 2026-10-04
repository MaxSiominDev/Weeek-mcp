#!/usr/bin/env python
"""Dump the shape of the internal (cookie-only) task payload: keys, types, URL
hosts, never real values. Raw JSON lands in git-ignored tests/fixtures/live/.

    python scripts/probe_internal.py --task 154 [--workspace 424242]

Cookie comes from `weeek-mcp login` storage or WEEEK_COOKIE. GETs only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from weeek_mcp.session.cookies import parse_cookie_header, to_header
from weeek_mcp.session.storage import load as load_session

BASE = "https://api.weeek.net"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.weeek.net/",
    "Origin": "https://app.weeek.net",
}
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "live"

# Top-level task fields the renderer reads; presence is reported explicitly.
# boardColumnId and projectId are not top level, they live inside locations[].
WANTED = [
    "title", "content", "priority", "type", "completed",
    "authorId", "assignees", "locations",
    "createdAt", "startDateTime", "dueDateTime",
    "comments", "commentsCount", "filesCount",
]


def shape(value: Any, depth: int = 0) -> Any:
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return ["<empty>"]
        return [shape(value[0], depth + 1), f"... ({len(value)} items)"]
    if isinstance(value, str):
        if value[:4] == "http":
            parts = urlsplit(value)
            return f"<url {parts.netloc}{parts.path}>"
        return f"<str len={len(value)}>"
    if isinstance(value, bool):
        return f"<bool {value}>"
    if value is None:
        return "<null>"
    return f"<{type(value).__name__}>"


def load_cookie() -> tuple[str, int | None]:
    raw = os.environ.get("WEEEK_COOKIE", "").strip()
    if raw:
        jar = parse_cookie_header(raw)
        return to_header(jar), None
    session = load_session()
    if session is None:
        print("No session. Run `weeek-mcp login --from-browser`, or set WEEEK_COOKIE.", file=sys.stderr)
        raise SystemExit(2)
    return to_header(session.cookies), session.workspace_id


async def get(client: httpx2.AsyncClient, cookie: str, path: str, **params: Any) -> Any:
    r = await client.get(f"{BASE}{path}", headers={**HEADERS, "Cookie": cookie}, params=params or None)
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype:
        print(f"  {path}: HTTP {r.status_code}, non-JSON ({ctype})", file=sys.stderr)
        return None
    body = r.json()
    if isinstance(body, dict) and body.get("success") is False:
        print(f"  {path}: FAILURE code={body.get('code')} message={body.get('message')!r}", file=sys.stderr)
        return None
    return body


def save(name: str, payload: Any) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{name}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"  (raw saved to tests/fixtures/live/{name}.json)")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", type=int, required=True)
    ap.add_argument("--workspace", type=int)
    args = ap.parse_args()

    cookie, ws_from_session = load_cookie()

    async with httpx2.AsyncClient(timeout=30, follow_redirects=True) as client:
        print("\n[1] GET /ws  (workspace list, and where the id comes from)")
        ws_body = await get(client, cookie, "/ws")
        if ws_body:
            print(json.dumps(shape(ws_body), indent=2, ensure_ascii=False))
            save("internal_ws", ws_body)

        ws = args.workspace or ws_from_session
        if not ws and isinstance(ws_body, dict):
            wss = ws_body.get("workspaces") or []
            ws = wss[0].get("id") if wss else None
        if not ws:
            print("Could not determine a workspace id; pass --workspace.", file=sys.stderr)
            return 2

        print(f"\n[2] GET /ws/{ws}/tm/tasks/{args.task}?withSubtasks=1  (the whole task)")
        task_body = await get(client, cookie, f"/ws/{ws}/tm/tasks/{args.task}", withSubtasks=1)
        if not task_body:
            return 1
        task = task_body.get("task") or {}
        print(json.dumps(shape(task_body), indent=2, ensure_ascii=False))
        save("internal_task", task_body)

        print("\n[3] Which fields the renderer needs are present:")
        for f in WANTED:
            mark = "yes" if f in task else "NO"
            print(f"    {mark:>3}  {f}")

        print("\n[4] Members endpoint (for resolving assignee ids to names)")
        members = await get(client, cookie, f"/ws/{ws}/members")
        if members:
            print(json.dumps(shape(members), indent=2, ensure_ascii=False))
            save("internal_members", members)

    print("\nDone. Paste sections [1]-[4] here (they contain no real values).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
