"""Optional smoke test for Strands + MCP integration.

This test is skipped unless `strands-agents` is installed in the environment.
It avoids NBA API calls by only listing tools / calling get_server_info.
"""

import sys

import pytest

pytest.importorskip("strands")
pytest.importorskip("strands.tools.mcp")

from mcp import StdioServerParameters, stdio_client
from strands.tools.mcp import MCPClient


@pytest.mark.asyncio
async def test_strands_mcp_client_can_list_tools_and_call_server_info():
    mcp_client = MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-u", "-m", "nba_mcp_server"],
            )
        )
    )

    with mcp_client:
        tools_resp = mcp_client.list_tools_sync()
        # Depending on strands/mcp versions, list_tools_sync may return either:
        # - a list[Tool]
        # - a response object with `.tools`
        tools = getattr(tools_resp, "tools", tools_resp)

        # Tool objects may be pydantic-like; accept multiple shapes across strands versions.
        tool_names = []
        for t in tools:
            name = (
                getattr(t, "name", None)
                or getattr(t, "tool_name", None)
                or (t.get("name") if isinstance(t, dict) else None)
                or (t.get("tool_name") if isinstance(t, dict) else None)
            )
            if name:
                tool_names.append(name)

        assert "get_server_info" in tool_names
        assert "resolve_player_id" in tool_names

        result = mcp_client.call_tool_sync(
            tool_use_id="test-server-info",
            name="get_server_info",
            arguments={},
        )
        # result is the MCP response payload (dict with content)
        text = ""
        try:
            text = result["content"][0]["text"]
        except Exception:
            text = str(result)

        assert "NBA MCP Server Info" in text


