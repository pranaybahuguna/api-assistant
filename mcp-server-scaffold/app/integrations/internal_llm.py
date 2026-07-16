"""Chat/vision clients for the internal LLM gateway (OpenAI-compatible).

get_ocr_model()  — vision-capable, for docx image OCR at ingestion.
get_chat_model() — general chat, for the OPTIONAL LLM guideline-scope
                   tagger at ingestion (SCOPE_TAGGER=llm). Both are
                   ingestion-time/offline tools; the live request path
                   (validate_oas etc.) still only ever calls embeddings.
"""
import os
from langchain_openai import ChatOpenAI


def get_ocr_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ.get("OCR_MODEL", "internal-llm"),
        base_url=os.environ.get("LLM_BASE_URL", "https://llm-gateway.example.com/v1"),
        api_key=os.environ.get("LLM_API_KEY", "changeme"),
        temperature=0,
    )


def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ.get("CHAT_MODEL", os.environ.get("OCR_MODEL", "internal-llm")),
        base_url=os.environ.get("LLM_BASE_URL", "https://llm-gateway.example.com/v1"),
        api_key=os.environ.get("LLM_API_KEY", "changeme"),
        temperature=0,
    )
