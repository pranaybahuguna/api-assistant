"""
search_api_registry — semantic search over endpoint/spec-summary chunks.
Accepts an optional api_id filter (obtained from search_api_referential)
to restrict results to one API — this is the api_id link in action.
"""
from app.models import SearchRegistryInput, SearchRegistryResult, RegistryHit
from app.rag.retriever import retrieve_with_scores
from app.rag.vector_store import Index

TOOL_DESCRIPTION = (
    "Semantic search over the Org API Registry (OpenAPI specs, one chunk "
    "per endpoint). Optionally filter by api_id to see only one API's "
    "endpoints — use search_api_referential first to find the api_id."
)


def search_api_registry(payload: SearchRegistryInput) -> SearchRegistryResult:
    filters = {"api_id": payload.api_id} if payload.api_id else None
    results = retrieve_with_scores(Index.REGISTRY, payload.query, k=payload.top_k, filters=filters)
    hits = [
        RegistryHit(
            api_id=d.metadata.get("api_id", "unknown"),
            api_name=d.metadata.get("api_name", "unknown"),
            endpoint=(f"{d.metadata['method']} {d.metadata['path']}"
                      if d.metadata.get("method") else None),
            chunk_type=d.metadata.get("type", "oas_operation"),
            content=d.page_content,
            score=float(score),
        )
        for d, score in results
    ]
    return SearchRegistryResult(hits=hits, summary=f"{len(hits)} matching chunk(s).")
