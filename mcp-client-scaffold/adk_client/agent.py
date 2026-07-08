"""
the API Assistant agent: internal custom-URL LLM + the four MCP tools served by the
API Assistant MCP server (over Streamable HTTP).
"""
from google.adk.agents import LlmAgent

from adk_client.internal_llm import get_internal_llm
from adk_client.mcp_toolset import build_mcp_toolset

INSTRUCTION = """You are the API Assistant, an assistant for the organization developers
and API designers.

Tool usage rules:
- To find WHICH API to use, call search_api_referential first; then use the
  returned api_id to filter search_api_registry for that API's endpoints.
- Write full descriptive sentences as search queries, not keywords.
- Pass OAS content to validate_oas / fix_oas exactly as given — never
  reformat it yourself first.
- If a search returns no good match, say so plainly; never invent an API.
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        model=get_internal_llm(),
        name="llm_at_org",
        description="the API Assistant — API Assistant agent",
        instruction=INSTRUCTION,
        tools=[build_mcp_toolset()],
    )


root_agent = build_agent()
