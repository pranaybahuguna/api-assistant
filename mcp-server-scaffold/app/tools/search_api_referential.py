"""
search_api_referential — discovery over the API inventory. Returns api_id
so the agent can follow up with a filtered search_api_registry call.
"""
import logging

from app.models import SearchReferentialInput, SearchReferentialResult, ReferentialHit
from app.rag.retriever import retrieve_with_scores
from app.rag.vector_store import Index

logger = logging.getLogger(__name__)


def search_api_referential(payload: SearchReferentialInput) -> SearchReferentialResult:
    results = retrieve_with_scores(Index.REFERENTIAL, payload.query, k=payload.top_k)
    hits = [
        ReferentialHit(
            api_id=d.metadata.get("api_id", "unknown"),
            api_name=d.metadata.get("api_name", "unknown"),
            description=d.page_content,
            url=d.metadata.get("url"),
            score=float(score),
            source_document=d.metadata.get("source"),
        )
        for d, score in results
    ]

    if hits:
        next_step = (f"Call search_api_registry with api_id='{hits[0].api_id}' (the best match — "
                     f"or another candidate's api_id if it fits the user's need better) to see "
                     f"that API's endpoints.")
    else:
        next_step = "No matching API found. Tell the user plainly — do not invent an API or a URL."

    logger.info("search_api_referential: query=%r top_k=%d -> %d hit(s)", payload.query, payload.top_k, len(hits))

    return SearchReferentialResult(hits=hits, summary=f"{len(hits)} candidate API(s).", next_step=next_step)
