"""
FastMCP entrypoint — the four tools exposed over the Model Context Protocol
(Streamable HTTP transport) at POST/GET /mcp.

Tool functions are plain `def` (not `async def`) on purpose: FastMCP runs
sync tools in a worker thread by default (run_in_thread=True), which keeps
the blocking Spectral subprocess / LLM / embeddings calls off the event
loop without any extra plumbing.

Run:
    python -m app.main
    # or: fastmcp run app.main:mcp --transport streamable-http --port 8080
"""
from dotenv import load_dotenv
load_dotenv()

from fastmcp import FastMCP

from app.models import (
    OASInput, ValidateOASResult, FixOASResult,
    SearchRegistryInput, SearchRegistryResult,
    SearchReferentialInput, SearchReferentialResult,
)
from app.tools import validate_oas as t_validate
from app.tools import fix_oas as t_fix
from app.tools import search_api_registry as t_registry
from app.tools import search_api_referential as t_referential

mcp = FastMCP(name="API Assistant — MCP Server", version="0.1.0")


@mcp.tool
def validate_oas(oas_content: str, format: str = "yaml", api_name: str | None = None) -> ValidateOASResult:
    """Validate an OpenAPI spec against API Design Guidelines.

    Runs the Spectral lint (findings enriched with rule explanations and
    suggested fixes from the ruleset lookup) plus a Guidelines Index
    retrieval for prose rules the linter can't check. Does not modify the
    spec — use fix_oas for that.
    """
    return t_validate.validate_oas(OASInput(oas_content=oas_content, format=format, api_name=api_name))


@mcp.tool
def fix_oas(oas_content: str, format: str = "yaml", api_name: str | None = None) -> FixOASResult:
    """Get a fix plan for an OpenAPI spec against API Design Guidelines.

    Does NOT rewrite the spec — apply the fixes yourself. Returns
    mechanical_fixes (each has a concrete suggested_fix from the ruleset —
    apply as stated), needs_judgment (a violation exists but the ruleset
    has no one-line fix — use rule_explanation to decide how to resolve
    it), and guideline_notes (prose context for rules Spectral can't check
    structurally). After editing, call validate_oas again to confirm.
    """
    return t_fix.fix_oas(OASInput(oas_content=oas_content, format=format, api_name=api_name))


@mcp.tool
def search_api_registry(query: str, top_k: int = 5, api_id: str | None = None) -> SearchRegistryResult:
    """Semantic search over the Org API Registry (OpenAPI specs, one chunk
    per endpoint plus one spec-summary chunk per API).

    Optionally filter by api_id to see only one API's endpoints — use
    search_api_referential first to find the api_id.
    """
    return t_registry.search_api_registry(SearchRegistryInput(query=query, top_k=top_k, api_id=api_id))


@mcp.tool
def search_api_referential(query: str, top_k: int = 5) -> SearchReferentialResult:
    """Find which Org API to use for a need described in natural language
    (e.g. "store client documents").

    Searches the API Referential inventory and returns candidates with
    their api_id for a follow-up search_api_registry call.
    """
    return t_referential.search_api_referential(SearchReferentialInput(query=query, top_k=top_k))


# Single Starlette app, built once — this is what `uvicorn app.main:app`
# serves in prod, and what the __main__ block below runs locally.
app = mcp.http_app(path="/mcp", transport="streamable-http")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
