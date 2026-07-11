"""Vision-capable client for the internal LLM gateway (OpenAI-compatible),
used only for docx image OCR — the one LLM-style call this server makes
beyond embeddings. Fixing a spec is the calling agent's job, not ours."""
import os
from langchain_openai import ChatOpenAI


def get_ocr_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ.get("OCR_MODEL", "internal-llm"),
        base_url=os.environ.get("LLM_BASE_URL", "https://llm-gateway.example.com/v1"),
        api_key=os.environ.get("LLM_API_KEY", "changeme"),
        temperature=0,
    )
