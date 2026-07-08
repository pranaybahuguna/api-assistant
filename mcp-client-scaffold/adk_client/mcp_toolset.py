"""
Connects to the API Assistant MCP server over Streamable HTTP. ADK
discovers the four tools (names, schemas, docstrings) directly from the MCP
protocol's tools/list — nothing is hand-wired here.
"""
import os

from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset


def build_mcp_toolset() -> McpToolset:
    headers = {}
    name = os.environ.get("API_ASSISTANT_AUTH_HEADER_NAME")
    value = os.environ.get("API_ASSISTANT_AUTH_HEADER_VALUE")
    if name and value:
        headers[name] = value

    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=os.environ.get("API_ASSISTANT_MCP_URL", "http://localhost:8080/mcp"),
            headers=headers or None,
        ),
    )
