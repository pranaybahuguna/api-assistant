"""
FastMCP entrypoint — the four tools exposed over the Model Context Protocol
(Streamable HTTP transport) at POST/GET /mcp.

Every tool's docstring here is written to stand on its own: the calling
agent may be a generic client with no custom system prompt telling it how
these tools relate to each other, so the workflow guidance (call order,
what to do with the result) lives in the docstrings themselves — which
`tools/list` surfaces to any MCP client regardless of its own prompt — and
every response also carries a `next_step` field spelling out what to do
with THIS result. Don't rely on a client-side instruction to know how to
chain these tools; if you change the workflow, update it here first.

Tool functions are plain `def` (not `async def`) on purpose: FastMCP runs
sync tools in a worker thread by default (run_in_thread=True), which keeps
the blocking Spectral subprocess / LLM / embeddings calls off the event
loop without any extra plumbing.

Run:
    python -m app.main
    # or: fastmcp run app.main:mcp --transport streamable-http --port 8080

Logging: each tool call is logged twice — once here, on arrival (tool name
+ raw arguments, before anything runs), and once inside app/tools/*.py, on
completion (a summary of what was found/returned). Together that's enough
to see what happened for every call without needing a debugger — check
stdout/stderr wherever the server process is running.
"""
import logging

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP(name="API Assistant — MCP Server", version="0.1.0")


@mcp.tool
def validate_oas(oas_content: str, format: str = "yaml", api_name: str | None = None) -> ValidateOASResult:
    """Validate an OpenAPI spec against API Design Guidelines. Call this
    whenever a user shares an OAS spec, asks if one is compliant, or after
    you (or the user) edit one following fix_oas's plan.

    Runs the Spectral lint (findings enriched with rule explanations and
    suggested fixes from the ruleset lookup) plus a Guidelines Index
    retrieval for prose rules the linter can't check. Read-only — never
    modifies oas_content. Pass the spec exactly as given/retrieved, never
    reformatted. If the user only asked you to validate, this report IS the
    final answer — do not proactively call fix_oas unless the user asks you
    to fix or correct the spec. Present the result as exactly four
    sections: (1) Spectral Lint Errors & Warnings (source=spectral-core),
    (2) Custom Ruleset Recommendations & Warnings (source=custom-ruleset, with
    rule_explanation/suggested_fix), (3) Org API Guideline Recommendations
    (source=rag, cited via source_document/source_section), (4) Summary &
    Next Steps. The response's next_step field restates this exactly —
    follow it.
    """
    logger.info("tools/call validate_oas: api_name=%s format=%s oas_content=%d chars",
                api_name, format, len(oas_content))
    return t_validate.validate_oas(OASInput(oas_content=oas_content, format=format, api_name=api_name))


@mcp.tool
def fix_oas(oas_content: str, format: str = "yaml", api_name: str | None = None) -> FixOASResult:
    """Get a fix plan for a non-compliant OpenAPI spec. Only call this if
    the user asks you to fix/correct the spec — validate_oas reporting
    is_valid=false is a precondition, not by itself a reason to call this;
    if the user only asked to validate, stop at the validate_oas report.

    Does NOT rewrite the spec — YOU (the calling agent) must edit
    oas_content yourself using this plan, then call validate_oas again on
    your edited version to confirm. Returns mechanical_fixes (each has a
    concrete suggested_fix from the ruleset — apply as stated),
    needs_judgment (a violation exists but the ruleset has no one-line fix
    — use rule_explanation to decide), and guideline_notes (prose context,
    each citing source_document/source_section it came from).
    """
    logger.info("tools/call fix_oas: api_name=%s format=%s oas_content=%d chars",
                api_name, format, len(oas_content))
    return t_fix.fix_oas(OASInput(oas_content=oas_content, format=format, api_name=api_name))


@mcp.tool
def search_api_registry(query: str, top_k: int = 5, api_id: str | None = None) -> SearchRegistryResult:
    """Semantic search over the Org API Registry (OpenAPI specs, one chunk
    per endpoint plus one spec-summary chunk per API) to find specific
    endpoints. Call this once you know which API you need.

    Pass api_id (from search_api_referential) to restrict results to one
    API — always do this if you already have an api_id, since an unfiltered
    search can return endpoints from unrelated APIs. If you don't know the
    api_id yet, call search_api_referential first instead of guessing. Each
    hit carries source_document (the OAS filename it came from) — cite it.
    """
    logger.info("tools/call search_api_registry: query=%r top_k=%d api_id=%s", query, top_k, api_id)
    return t_registry.search_api_registry(SearchRegistryInput(query=query, top_k=top_k, api_id=api_id))


@mcp.tool
def search_api_referential(query: str, top_k: int = 5) -> SearchReferentialResult:
    """Find which Org API to use for a need described in natural language
    (e.g. "store client documents"). Call this FIRST whenever a user
    describes a need but doesn't name a specific, known API — do not guess
    or invent an API name/id yourself.

    Searches the API Referential inventory and returns candidates with
    their api_id — pass that api_id into search_api_registry next to see
    the chosen API's actual endpoints. If no candidate fits, say so
    plainly instead of proceeding with a guess. Each hit carries
    source_document (the inventory filename it came from) — cite it.
    """
    logger.info("tools/call search_api_referential: query=%r top_k=%d", query, top_k)
    return t_referential.search_api_referential(SearchReferentialInput(query=query, top_k=top_k))


# Single Starlette app, built once — this is what `uvicorn app.main:app`
# serves in prod, and what the __main__ block below runs locally.
app = mcp.http_app(path="/mcp", transport="streamable-http")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
