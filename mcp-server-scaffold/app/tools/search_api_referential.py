"""
search_api_referential — discovery over the API inventory. Returns api_id
so the agent can follow up with a filtered search_api_registry call.
"""
from app.models import SearchReferentialInput, SearchReferentialResult, ReferentialHit
from app.rag.retriever import retrieve_with_scores
from app.rag.vector_store import Index

TOOL_DESCRIPTION = (
    "Find which Org API to use for a need described in natural language "
    "(e.g. 'store documents'). Searches the API Referential inventory and "
    "returns candidates with their api_id for follow-up registry searches."
)


def search_api_referential(payload: SearchReferentialInput) -> SearchReferentialResult:
    results = retrieve_with_scores(Index.REFERENTIAL, payload.query, k=payload.top_k)
    hits = [
        ReferentialHit(
            api_id=d.metadata.get("api_id", "unknown"),
            api_name=d.metadata.get("api_name", "unknown"),
            description=d.page_content,
            url=d.metadata.get("url"),
            score=float(score),
        )
        for d, score in results
    ]
    return SearchReferentialResult(hits=hits, summary=f"{len(hits)} candidate API(s).")
