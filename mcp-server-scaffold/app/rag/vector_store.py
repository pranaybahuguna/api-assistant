"""
Vector store factory. POC default = FAISS saved to local files (no database
to install — perfect for a laptop demo). Later, flip VECTOR_BACKEND to
"pgvector" or "opensearch" in .env and fill the matching connection
settings: nothing else in the codebase changes, because every caller only
ever sees the LangChain VectorStore interface. Add a new backend by adding
one more `elif` branch here — call sites never change.

FAISS persistence model: each index lives in its own folder under
settings.faiss_dir (e.g. ./vector_data/guidelines/). save() must be called
after adding documents — FAISS is in-memory until saved.
"""
from enum import Enum
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.vectorstores import VectorStore

from app.config import get_settings
from app.rag.embeddings import get_embeddings


class Index(str, Enum):
    GUIDELINES = "guidelines"
    REGISTRY = "registry"
    REFERENTIAL = "referential"


_faiss_cache: dict[Index, FAISS] = {}


def _faiss_path(index: Index) -> Path:
    return Path(get_settings().faiss_dir) / index.value


def get_vector_store(index: Index) -> VectorStore:
    settings = get_settings()

    if settings.vector_backend == "faiss":
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

    elif settings.vector_backend == "pgvector":
        # Deferred import so the POC doesn't need psycopg installed.
        from langchain_postgres import PGVector
        return PGVector(
            embeddings=get_embeddings(),
            collection_name=f"{index.value}_index",
            connection=settings.vector_db_url,
            use_jsonb=True,
        )

    elif settings.vector_backend == "opensearch":
        # Deferred import so the POC doesn't need opensearch-py installed.
        from langchain_community.vectorstores import OpenSearchVectorSearch
        auth = (settings.opensearch_username, settings.opensearch_password) if settings.opensearch_username else None
        return OpenSearchVectorSearch(
            opensearch_url=settings.opensearch_url,
            index_name=f"{index.value}_index",
            embedding_function=get_embeddings(),
            http_auth=auth,
            verify_certs=settings.opensearch_verify_certs,
        )

    raise ValueError(f"Unknown vector backend: {settings.vector_backend}")


def save_faiss(index: Index) -> None:
    """Persist a FAISS index to disk. Call after ingestion. No-op for pgvector."""
    if get_settings().vector_backend != "faiss":
        return
    store = _faiss_cache.get(index)
    if store is not None:
        path = _faiss_path(index)
        path.mkdir(parents=True, exist_ok=True)
        store.save_local(str(path))
