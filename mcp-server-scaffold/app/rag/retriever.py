"""
Retrieval helpers. FAISS supports metadata filtering via a filter dict
(exact-match), which we use for the api_id link between Referential and
Registry.
"""
from typing import Any
from langchain_core.documents import Document

from app.rag.vector_store import Index, get_vector_store


def retrieve_with_scores(
    index: Index, query: str, k: int = 5, filters: dict[str, Any] | None = None
) -> list[tuple[Document, float]]:
    store = get_vector_store(index)
    results = store.similarity_search_with_score(query, k=k, filter=filters)
    # drop the bootstrap placeholder if it sneaks into results
    return [(d, s) for d, s in results if not d.metadata.get("bootstrap")]


def retrieve_guidelines(query: str, k: int = 5) -> list[Document]:
    return [d for d, _ in retrieve_with_scores(Index.GUIDELINES, query, k=k)]


def retrieve_referential(query: str, k: int = 5) -> list[tuple[Document, float]]:
    return retrieve_with_scores(Index.REFERENTIAL, query, k=k)


def retrieve_registry(
    query: str, k: int = 5, api_id: str | None = None
) -> list[tuple[Document, float]]:
    filters = {"api_id": api_id} if api_id else None
    return retrieve_with_scores(Index.REGISTRY, query, k=k, filters=filters)
