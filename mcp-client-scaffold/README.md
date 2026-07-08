# the API Assistant — Google ADK client (custom internal LLM + MCP tools)

An ADK agent that:
1. Talks to YOUR internal Org-hosted LLM via its custom base URL
   (LiteLlm with api_base override — OpenAI wire format to your endpoint,
   nothing leaves the premises).
2. Connects to the API Assistant MCP server over Streamable HTTP via
   ADK's `McpToolset` (validate_oas, fix_oas, search_api_registry,
   search_api_referential) — tool names, schemas, and descriptions are
   discovered live from the server's `tools/list`, not hand-wired here.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set your internal LLM URL/key + server URL
python -m adk_client.run_cli
```

Try: "Which API can I use to store client documents, and show me its endpoints."
The agent should chain search_api_referential -> search_api_registry(api_id=...).
