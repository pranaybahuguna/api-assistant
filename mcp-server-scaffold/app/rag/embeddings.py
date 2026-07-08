"""
Embedding model wrapper — points at the internal Org LLM gateway
(OpenAI-compatible /embeddings route). Single place to swap if the
gateway's contract differs.
"""
from langchain_openai import OpenAIEmbeddings
from app.config import get_settings


def get_embeddings() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(model=s.embedding_model, base_url=s.llm_base_url, api_key=s.llm_api_key)
