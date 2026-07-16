"""
FAISS vector store, one index per folder under ./vector_data/<index>/.

No in-memory cache — every call loads straight from disk. A cache means
having to answer "when is it stale," and that's not worth the complexity
for a demo-sized index: FAISS.load_local() is fast, and always reading
from disk means the server always sees the latest ingested data, in any
process, with no restart or invalidation logic required.
"""
import os
from enum import Enum
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.vectorstores import VectorStore

from app.rag.embeddings import get_embeddings


class Index(str, Enum):
    GUIDELINES = "guidelines"
    REGISTRY = "registry"
    REFERENTIAL = "referential"


def _faiss_path(index: Index) -> Path:
    return Path(os.environ.get("FAISS_DIR", "./vector_data")) / index.value


def get_vector_store(index: Index) -> VectorStore:
    path = _faiss_path(index)
    embeddings = get_embeddings()
    if path.exists():
        return FAISS.load_local(str(path), embeddings, allow_dangerous_deserialization=True)
    # Bootstrap an empty index; real content arrives via the ingestion pipeline.
    return FAISS.from_texts(["__init__"], embeddings, metadatas=[{"bootstrap": True}])


def save_faiss(index: Index, store: VectorStore) -> None:
    """Persist a FAISS index to disk. Call after ingestion."""
    path = _faiss_path(index)
    path.mkdir(parents=True, exist_ok=True)
    store.save_local(str(path))


def save_guideline_summary(text: str) -> None:
    """Persist the consolidated guidelines summary (app/ingestion/summarize.py)
    as a plain text file next to the guidelines FAISS index — it's read
    whole, never embedded/searched, so it doesn't belong in the vector store."""
    path = _faiss_path(Index.GUIDELINES)
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.txt").write_text(text)


def load_guideline_summary() -> str | None:
    """The persisted summary, or None if ingestion hasn't produced one yet
    (e.g. SCOPE_TAGGER=keyword was used, or the guidelines index is empty)."""
    summary_path = _faiss_path(Index.GUIDELINES) / "summary.txt"
    return summary_path.read_text() if summary_path.exists() else None
