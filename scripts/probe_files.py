#!/usr/bin/env python
"""Find which endpoint serves a task's file list; the task payload only has a
filesCount. Prints shapes, saves the first hit to tests/fixtures/live/."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx2

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from probe_internal import FIXTURES, HEADERS, load_cookie, shape

BASE = "https://api.weeek.net"


async def get(client: httpx2.AsyncClient, cookie: str, path: str, **params) -> dict | None:
    r = await client.get(f"{BASE}{path}", headers={**HEADERS, "Cookie": cookie}, params=params or None)
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype:
        print(f"  {path} {params or ''}: HTTP {r.status_code}, non-JSON ({ctype})")
        return None
    body = r.json()
    if isinstance(body, dict) and body.get("success") is False:
        print(f"  {path} {params or ''}: FAILURE code={body.get('code')} {body.get('message')!r}")
        return None
    return body


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", type=int, required=True)
    ap.add_argument("--workspace", type=int)
    args = ap.parse_args()

    cookie, ws_from_session = load_cookie()
    ws = args.workspace or ws_from_session
    if not ws:
        print("No workspace; pass --workspace.", file=sys.stderr)
        return 2

    candidates = [
        (f"/ws/{ws}/tm/tasks/{args.task}/files", {}),
        (f"/ws/{ws}/tm/tasks/{args.task}/attachments", {}),
        (f"/ws/{ws}/tm/files", {"taskId": args.task}),
        (f"/ws/{ws}/files", {"taskId": args.task}),
    ]

    hit = None

    async with httpx2.AsyncClient(timeout=30, follow_redirects=True) as client:
        for path, params in candidates:
            print(f"\ntry: GET {path} {params or ''}")
            body = await get(client, cookie, path, **params)
            if body is not None:
                print(json.dumps(shape(body), indent=2, ensure_ascii=False))
                hit = hit or (path, body)

        print("\nvariant: the task fetch itself, with withFiles=1")
        task_body = await get(
            client, cookie, f"/ws/{ws}/tm/tasks/{args.task}", withSubtasks=1, withFiles=1
        )
        if task_body:
            task = task_body.get("task") or {}
            extra = sorted(set(task) - set(await _baseline_keys(client, cookie, ws, args.task)))
            print(f"  keys added by withFiles=1: {extra or 'none'}")
            if "files" in task:
                print(json.dumps(shape(task["files"]), indent=2, ensure_ascii=False))
                hit = hit or ("task.files", task["files"])

        print("\nsupport: GET /ws/{ws}/tm/projects  (project names for the header)")
        projects = await get(client, cookie, f"/ws/{ws}/tm/projects")
        if projects:
            print(json.dumps(shape(projects), indent=2, ensure_ascii=False))
            FIXTURES.mkdir(parents=True, exist_ok=True)
            (FIXTURES / "internal_projects.json").write_text(
                json.dumps(projects, indent=2, ensure_ascii=False)
            )
            print("  (raw saved to tests/fixtures/live/internal_projects.json)")

    if hit:
        name = "internal_task_files.json"
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / name).write_text(json.dumps(hit[1], indent=2, ensure_ascii=False))
        print(f"\nWinner: {hit[0]} (raw saved to tests/fixtures/live/{name})")
    else:
        print("\nNo endpoint answered with a file list.")
    return 0


async def _baseline_keys(client, cookie, ws, task) -> set:
    body = await get(client, cookie, f"/ws/{ws}/tm/tasks/{task}", withSubtasks=1)
    return set((body or {}).get("task") or {})


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
