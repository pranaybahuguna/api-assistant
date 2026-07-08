"""
Chat client for the internal Org-hosted LLM (OpenAI-compatible gateway).
Used by fix_oas for the rewrite step. Same base_url/api_key pattern as the
embeddings wrapper.
"""
from langchain_openai import ChatOpenAI
from app.config import get_settings


def get_chat_model() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(model=s.chat_model, base_url=s.llm_base_url, api_key=s.llm_api_key, temperature=0)
