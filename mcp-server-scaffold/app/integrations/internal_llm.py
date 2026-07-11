"""Chat client for the internal Org-hosted LLM (OpenAI-compatible gateway).
Used by fix_oas for the rewrite step and by loaders.py for image OCR."""
import os
from langchain_openai import ChatOpenAI


def get_chat_model(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or os.environ.get("CHAT_MODEL", "internal-llm"),
        base_url=os.environ.get("LLM_BASE_URL", "https://llm-gateway.example.com/v1"),
        api_key=os.environ.get("LLM_API_KEY", "changeme"),
        temperature=0,
    )
