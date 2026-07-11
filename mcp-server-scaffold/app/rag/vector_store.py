"""
FAISS vector store, one index per folder under ./vector_data/<index>/.
FAISS is in-memory until save_faiss() is called — the ingestion pipeline
calls it after every add_documents.

The cache is keyed on the index file's mtime, not just its presence: a
long-running server process (started before ingestion, or before a later
re-ingestion) must pick up a file that changed on disk since it was last
loaded, without needing a restart. A plain "cache forever once loaded"
dict would silently keep serving a stale (or empty bootstrap) index
forever in that case.
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


_faiss_cache: dict[Index, tuple[float | None, FAISS]] = {}  # index -> (mtime seen, store)


def _faiss_path(index: Index) -> Path:
    return Path(os.environ.get("FAISS_DIR", "./vector_data")) / index.value


def _index_file(index: Index) -> Path:
    return _faiss_path(index) / "index.faiss"


def get_vector_store(index: Index) -> VectorStore:
    index_file = _index_file(index)
    current_mtime = index_file.stat().st_mtime if index_file.exists() else None

    cached = _faiss_cache.get(index)
    if cached is not None and cached[0] == current_mtime:
        return cached[1]

    path = _faiss_path(index)
    embeddings = get_embeddings()
    if path.exists():
        store = FAISS.load_local(str(path), embeddings, allow_dangerous_deserialization=True)
    else:
        # Bootstrap an empty index; real content arrives via the ingestion pipeline.
        store = FAISS.from_texts(["__init__"], embeddings, metadatas=[{"bootstrap": True}])
    _faiss_cache[index] = (current_mtime, store)
    return store


def save_faiss(index: Index) -> None:
    """Persist a FAISS index to disk. Call after ingestion."""
    cached = _faiss_cache.get(index)
    if cached is not None:
        store = cached[1]
        path = _faiss_path(index)
        path.mkdir(parents=True, exist_ok=True)
        store.save_local(str(path))
        _faiss_cache[index] = (_index_file(index).stat().st_mtime, store)
