"""Chat/vision clients for an OpenAI-compatible LLM gateway.

No connection details ship in this repo — model names, base URL, and API
key must all be provided via environment variables.
"""
import os
from langchain_openai import ChatOpenAI


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set — configure your LLM gateway entirely via "
            "environment variables; this repo ships no defaults."
        )
    return value


def get_ocr_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=_require("OCR_MODEL"),
        base_url=_require("LLM_BASE_URL"),
        api_key=_require("LLM_API_KEY"),
        temperature=0,
    )
