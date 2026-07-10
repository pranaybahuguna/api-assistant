from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)

# Point LiteLLM at your internal OpenAI-compatible endpoint.
# The "openai/" prefix tells LiteLLM to use the OpenAI-format client;
# api_base + api_key redirect it to your internal LLM instead of api.openai.com.
internal_llm = LiteLlm(
    model="openai/your-internal-model-name",   # whatever model id your endpoint expects
    api_base="https://your-internal-llm/v1",    # must end in /v1 for OpenAI-compatible APIs
)

root_agent = LlmAgent(
    model=internal_llm,
    name="assistant",
    instruction=(
        "You are a helpful assistant. Use the available tools when the user "
        "asks about weather or SIP/investment calculations. Otherwise answer "
        "directly."
    ),
    tools=[
        MCPToolset(
            connection_params=StreamableHTTPConnectionParams(
                url="http://localhost:8765/mcp",
            ),
        )
    ],
)
