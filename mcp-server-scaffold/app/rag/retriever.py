"""
Retrieval helpers. Two access patterns against the same FAISS stores:

- Semantic (retrieve_with_scores / retrieve_guidelines): embed a query,
  nearest-neighbour search. Used when we don't know which chunk we want.
- Direct (enumerate_guideline_chunks / get_section_chunks /
  build_guidelines_toc): walk the docstore's metadata without any
  embedding call. Used when we know exactly what we want — a named
  section, or the corpus's table of contents. Cheaper and deterministic;
  no reason to pay for a similarity search to fetch a chunk by name.

FAISS supports metadata filtering via a filter dict (exact-match), which
we use for the api_id link between Referential and Registry.
"""
from typing import Any
from langchain_core.documents import Document

from app.rag.vector_store import Index, get_vector_store, load_guideline_summary


def retrieve_with_scores(
    index: Index, query: str, k: int = 5, filters: dict[str, Any] | None = None
) -> list[tuple[Document, float]]:
    store = get_vector_store(index)
    results = store.similarity_search_with_score(query, k=k, filter=filters)
    # drop the bootstrap placeholder if it sneaks into results
    return [(d, s) for d, s in results if not d.metadata.get("bootstrap")]


def retrieve_guidelines(query: str, k: int = 5) -> list[Document]:
    return [d for d, _ in retrieve_with_scores(Index.GUIDELINES, query, k=k)]


def enumerate_guideline_chunks() -> list[Document]:
    """Every real chunk in the guidelines store, straight from the docstore
    — no embedding call, no similarity ranking."""
    store = get_vector_store(Index.GUIDELINES)
    docs = getattr(store, "docstore", None)
    if docs is None or not hasattr(docs, "_dict"):
        return []
    return [d for d in docs._dict.values() if not d.metadata.get("bootstrap")]


def get_section_chunks(section: str, document: str | None = None) -> list[Document]:
    """All chunks whose section heading matches `section` (case-insensitive
    substring, so 'idempotency' finds '4. Idempotency'), optionally
    restricted to one source document."""
    needle = section.strip().lower()
    matches = []
    for d in enumerate_guideline_chunks():
        chunk_section = (d.metadata.get("section") or "").lower()
        if needle not in chunk_section:
            continue
        if document and d.metadata.get("source") != document:
            continue
        matches.append(d)
    return matches


def get_guidelines_summary() -> str | None:
    """The consolidated whole-corpus guidelines summary (app/ingestion/
    summarize.py), or None if it hasn't been generated (SCOPE_TAGGER was
    "keyword" at ingestion, or nothing's ingested yet). No embedding call —
    reads the persisted text straight from disk, same as build_guidelines_toc."""
    return load_guideline_summary()


def build_guidelines_toc() -> str:
    """Compact one-line-per-document table of contents, built from chunk
    metadata: 'doc.docx: 1. Naming; 2. Pagination; ...'. Empty string if
    nothing is ingested yet."""
    sections_by_doc: dict[str, set[str]] = {}
    for d in enumerate_guideline_chunks():
        source = d.metadata.get("source")
        section = d.metadata.get("section")
        if source and section:
            sections_by_doc.setdefault(source, set()).add(section)
    return "\n".join(
        f"{doc}: " + "; ".join(sorted(sections))
        for doc, sections in sorted(sections_by_doc.items())
    )
