"""
search_api_registry — semantic search over endpoint/spec-summary chunks.
Accepts an optional api_id filter (obtained from search_api_referential)
to restrict results to one API — this is the api_id link in action.
"""
import logging

from app.models import SearchRegistryInput, SearchRegistryResult, RegistryHit
from app.rag.retriever import retrieve_with_scores
from app.rag.vector_store import Index

logger = logging.getLogger(__name__)


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
            source_document=d.metadata.get("source"),
        )
        for d, score in results
    ]

    distinct_apis = {h.api_id for h in hits}
    if not hits:
        next_step = ("No matching endpoints found. If you haven't already, call "
                      "search_api_referential first to confirm which API to search.")
    elif not payload.api_id and len(distinct_apis) > 1:
        next_step = ("Results span multiple APIs — call search_api_referential to pick the "
                      "right one, then re-run this search with that api_id for focused results.")
    else:
        next_step = "Use these endpoint(s) directly to answer the user's question."

    logger.info(
        "search_api_registry: query=%r api_id=%s top_k=%d -> %d hit(s) across %d API(s)",
        payload.query, payload.api_id, payload.top_k, len(hits), len(distinct_apis),
    )

    return SearchRegistryResult(hits=hits, summary=f"{len(hits)} matching chunk(s).", next_step=next_step)
