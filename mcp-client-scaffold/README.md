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

## The tool-chaining workflow lives on the server, not here

`adk_client/agent.py`'s `INSTRUCTION` reinforces the tool-usage order, but
it's not load-bearing — treat it as a convenience for this specific
reference client, not the source of truth. The actual guidance (when to
call each tool, what to do with the result) lives in the MCP server's tool
docstrings and each response's `next_step` field (see
`mcp-server-scaffold/README.md`'s "Self-guiding tools" section), because a
production caller may be a generic MCP client you don't control and can't
give a custom system prompt to. If this repo's agent ever behaves
differently from a bare-bones MCP client with no custom instructions at
all, that's a bug in the server's docstrings/next_step logic, not
something to patch around here.
