"""The MCP surface: a single tool that reads one task."""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from . import config, service
from .errors import WeeekError
from .url import TaskRefError

log = logging.getLogger("weeek_mcp")

DESCRIPTION = """\
Read a single Weeek task in full: title, status, description, every comment, and \
every attached file. Accepts any Weeek task link: the board URL with a task open \
(the one with m_task_id in its query string), the /ws/{id}/task/{id} permalink, or \
a bare numeric task id.

Images (screenshots, pasted pictures in comments) are downloaded to /tmp and \
reported as absolute file paths. They are NOT included in this tool's output, so \
open them with the Read tool to actually see them.

This tool does not search, list or modify anything. It reads one task at a time \
and cannot write to Weeek at all. To read a different task, call it again with \
that task's link.\
"""


def build() -> MCPServer:
    mcp = MCPServer("weeek")

    @mcp.tool(
        title="Read a Weeek task",
        description=DESCRIPTION,
        annotations={"readOnlyHint": True, "openWorldHint": True},
        structured_output=False,
    )
    async def weeek_get_task(
        url: Annotated[
            str,
            Field(
                description=(
                    "A Weeek task link exactly as copied from the browser, or a bare "
                    "numeric task id. Board links work as long as the task is open in "
                    "them, i.e. the address contains m_task_id."
                )
            ),
        ],
    ) -> CallToolResult:
        # Read per call so `weeek-mcp login` works without a restart.
        try:
            markdown = await service.get_task(url, config.load())
        except (WeeekError, TaskRefError, config.ConfigError) as exc:
            # A genuine bug should still crash, not become advice.
            log.warning("weeek_get_task failed: %s", type(exc).__name__)
            return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)

        return CallToolResult(content=[TextContent(type="text", text=markdown)])

    return mcp
