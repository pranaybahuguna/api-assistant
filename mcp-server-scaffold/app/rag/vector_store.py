"""
FAISS vector store, one index per folder under ./vector_data/<index>/.
FAISS is in-memory until save_faiss() is called — the ingestion pipeline
calls it after every add_documents.
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


_faiss_cache: dict[Index, FAISS] = {}


def _faiss_path(index: Index) -> Path:
    return Path(os.environ.get("FAISS_DIR", "./vector_data")) / index.value


def get_vector_store(index: Index) -> VectorStore:
    if index in _faiss_cache:
        return _faiss_cache[index]

    path = _faiss_path(index)
    embeddings = get_embeddings()
    if path.exists():
        store = FAISS.load_local(str(path), embeddings, allow_dangerous_deserialization=True)
    else:
        # Bootstrap an empty index; real content arrives via the ingestion pipeline.
        store = FAISS.from_texts(["__init__"], embeddings, metadatas=[{"bootstrap": True}])
    _faiss_cache[index] = store
    return store


def save_faiss(index: Index) -> None:
    """Persist a FAISS index to disk. Call after ingestion."""
    store = _faiss_cache.get(index)
    if store is not None:
        path = _faiss_path(index)
        path.mkdir(parents=True, exist_ok=True)
        store.save_local(str(path))
