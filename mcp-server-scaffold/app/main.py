"""
FastMCP entrypoint — the four tools exposed over the Model Context Protocol
(Streamable HTTP transport) at POST/GET /mcp, so any MCP-aware client (the
ADK client via McpToolset, or the API Assistant directly) gets tool discovery and
JSON schemas from the protocol itself instead of a hand-rolled REST catalogue.

the API gateway fronts this in prod; the ASGI middleware only checks the header
the API gateway injects (off by default for local dev via .env).

Tool functions are plain `def` (not `async def`) on purpose: FastMCP runs
sync tools in a worker thread by default (run_in_thread=True), which keeps
the blocking Spectral subprocess / LLM / embeddings calls off the event
loop without any extra plumbing.

Run:
    python -m app.main
    # or: fastmcp run app.main:mcp --transport streamable-http --port 8080
"""
import logging

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings
from app.integrations.spectral import SpectralError
from app.models import (
    OASInput, ValidateOASResult, FixOASResult,
    SearchRegistryInput, SearchRegistryResult,
    SearchReferentialInput, SearchReferentialResult,
)
from app.tools import validate_oas as t_validate
from app.tools import fix_oas as t_fix
from app.tools import search_api_registry as t_registry
from app.tools import search_api_referential as t_referential
from app.tools.fix_oas import LLMResponseError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Errors callers are meant to see verbatim (bad input, tool misconfig, etc.)
# — everything else is logged in full here and masked from the client by
# mask_error_details, since a raw traceback is not something to hand back
# over the API gateway to an arbitrary caller.
_EXPECTED_ERRORS = (SpectralError, LLMResponseError)

mcp = FastMCP(name="API Assistant — MCP Server", version="0.1.0", mask_error_details=True)


class the API gatewayHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        if s.require_apigee_header and s.apigee_verified_header not in request.headers:
            return JSONResponse({"detail": "Missing the API gateway verification header"}, status_code=401)
        return await call_next(request)


def _guarded(tool_name: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _EXPECTED_ERRORS as e:
        logger.warning("%s: %s", tool_name, e)
        raise ToolError(str(e)) from e
    except Exception:
        logger.exception("%s: unhandled error", tool_name)
        raise


@mcp.tool
def validate_oas(oas_content: str, format: str = "yaml", api_name: str | None = None) -> ValidateOASResult:
    """Validate an OpenAPI spec against API Design Guidelines.

    Runs the Spectral lint (findings enriched with rule explanations and
    suggested fixes from the ruleset lookup) plus a Guidelines Index
    retrieval for prose rules the linter can't check. Does not modify the
    spec — use fix_oas for that.
    """
    payload = OASInput(oas_content=oas_content, format=format, api_name=api_name)
    return _guarded("validate_oas", t_validate.validate_oas, payload)


@mcp.tool
def fix_oas(oas_content: str, format: str = "yaml", api_name: str | None = None) -> FixOASResult:
    """Fix an OpenAPI spec so it complies with API Design Guidelines.

    Returns the corrected spec, the list of changes made, and any
    violations that could not be auto-fixed.
    """
    payload = OASInput(oas_content=oas_content, format=format, api_name=api_name)
    return _guarded("fix_oas", t_fix.fix_oas, payload)


@mcp.tool
def search_api_registry(query: str, top_k: int = 5, api_id: str | None = None) -> SearchRegistryResult:
    """Semantic search over the Org API Registry (OpenAPI specs, one chunk
    per endpoint plus one spec-summary chunk per API).

    Optionally filter by api_id to see only one API's endpoints — use
    search_api_referential first to find the api_id.
    """
    payload = SearchRegistryInput(query=query, top_k=top_k, api_id=api_id)
    return _guarded("search_api_registry", t_registry.search_api_registry, payload)


@mcp.tool
def search_api_referential(query: str, top_k: int = 5) -> SearchReferentialResult:
    """Find which Org API to use for a need described in natural language
    (e.g. "store client documents").

    Searches the API Referential inventory and returns candidates with
    their api_id for a follow-up search_api_registry call.
    """
    payload = SearchReferentialInput(query=query, top_k=top_k)
    return _guarded("search_api_referential", t_referential.search_api_referential, payload)


# Single Starlette app, built once — this is what `uvicorn app.main:app` serves
# in prod, and what the __main__ block below runs locally, so the the API gateway
# middleware is never accidentally left out of one of the two paths.
app = mcp.http_app(path="/mcp", transport="streamable-http", middleware=[Middleware(the API gatewayHeaderMiddleware)])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
