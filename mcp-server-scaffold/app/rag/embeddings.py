"""
Embedding model factory. "openai" hits an OpenAI-wire-compatible /embeddings
route (batched). "rest" hits a custom internal gateway one text at a time
with a different payload shape and optional custom TLS trust (see
rest_embeddings.py). Switch via EMBEDDING_BACKEND in .env — every caller
only sees the LangChain Embeddings interface either way.
"""
from langchain_core.embeddings import Embeddings

from app.config import get_settings


def get_embeddings() -> Embeddings:
    s = get_settings()

    if s.embedding_backend == "rest":
        from app.rag.rest_embeddings import RestEmbeddings
        return RestEmbeddings()

    if s.embedding_backend == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=s.embedding_model, base_url=s.llm_base_url, api_key=s.llm_api_key)

    raise ValueError(f"Unknown embedding backend: {s.embedding_backend}")
