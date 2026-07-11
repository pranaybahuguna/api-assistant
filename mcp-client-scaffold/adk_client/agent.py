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
- fix_oas does NOT rewrite the spec — it returns a fix plan
  (mechanical_fixes with a concrete suggested_fix to apply as stated,
  needs_judgment findings with no one-line fix where you must use
  rule_explanation and guideline_notes to decide, and guideline_notes for
  prose context). YOU write the corrected spec yourself from that plan and
  show it to the user. After editing, call validate_oas again on your
  result to confirm the fixes actually resolved the findings.
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
