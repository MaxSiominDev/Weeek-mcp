"""The MCP surface, driven through a real in-process client."""

from __future__ import annotations

import pytest
from mcp.client import Client

from weeek_mcp import config, server, service
from weeek_mcp.config import Config, ConfigError
from weeek_mcp.errors import SessionExpired


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: Config(session=None))


async def test_the_server_exposes_exactly_one_read_only_tool(configured):
    async with Client(server.build()) as client:
        tools = (await client.list_tools()).tools

    assert [t.name for t in tools] == ["weeek_get_task"]
    assert tools[0].annotations.read_only_hint is True


async def test_the_description_states_where_images_go(configured):
    async with Client(server.build()) as client:
        tool = (await client.list_tools()).tools[0]

    # The model has no other way to learn the screenshots exist.
    assert "Read tool" in tool.description
    assert "does not search" in tool.description


async def test_a_task_comes_back_as_one_text_block(monkeypatch, configured):
    async def fake(url, cfg, **kwargs):
        return f"# Rendered {url}"

    monkeypatch.setattr(service, "get_task", fake)

    async with Client(server.build()) as client:
        result = await client.call_tool("weeek_get_task", {"url": "154"})

    assert result.is_error in (False, None)
    assert [block.type for block in result.content] == ["text"]
    assert result.content[0].text == "# Rendered 154"


async def test_a_dead_session_reaches_the_model_with_its_recovery_advice(monkeypatch, configured):
    """The message is the whole point: a sanitised 'Internal server error' would
    leave the model with no idea that `weeek-mcp login` is the fix."""

    async def fake(url, cfg, **kwargs):
        raise SessionExpired()

    monkeypatch.setattr(service, "get_task", fake)

    async with Client(server.build()) as client:
        result = await client.call_tool("weeek_get_task", {"url": "154"})

    assert result.is_error is True
    assert "weeek-mcp login" in result.content[0].text


async def test_a_bad_link_explains_what_to_paste_instead(monkeypatch, configured):
    async with Client(server.build()) as client:
        result = await client.call_tool(
            "weeek_get_task", {"url": "https://app.weeek.net/ws/424242/project/1/board/1"}
        )

    assert result.is_error is True
    assert "m_task_id" in result.content[0].text


async def test_a_missing_session_is_reported_rather_than_swallowed(monkeypatch):
    def unconfigured():
        raise ConfigError("No Weeek browser session stored. Run `weeek-mcp login`.")

    monkeypatch.setattr(config, "load", unconfigured)

    async with Client(server.build()) as client:
        result = await client.call_tool("weeek_get_task", {"url": "154"})

    assert result.is_error is True
    assert "weeek-mcp login" in result.content[0].text
