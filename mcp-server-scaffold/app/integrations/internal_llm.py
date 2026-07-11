"""Clients for the internal Org-hosted LLM gateway (OpenAI-compatible).
get_chat_model() is used by fix_oas for the rewrite step. get_ocr_model()
is used by loaders.py for docx image OCR — same gateway, but OCR_MODEL
lets it point at a distinct vision/OCR deployment instead of CHAT_MODEL."""
import os
from langchain_openai import ChatOpenAI


def get_chat_model(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or os.environ.get("CHAT_MODEL", "internal-llm"),
        base_url=os.environ.get("LLM_BASE_URL", "https://llm-gateway.example.com/v1"),
        api_key=os.environ.get("LLM_API_KEY", "changeme"),
        temperature=0,
    )


def get_ocr_model() -> ChatOpenAI:
    return get_chat_model(model=os.environ.get("OCR_MODEL"))
