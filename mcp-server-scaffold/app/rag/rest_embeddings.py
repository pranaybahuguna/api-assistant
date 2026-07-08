"""
REST-based embeddings client for internal LLM gateways that don't speak the
batched OpenAI /embeddings wire format — one text per HTTP call, a
{"model", "input": "<single string>"} payload, and (optionally) a custom
trust store instead of the system CA bundle. Implements LangChain's
Embeddings interface so it's a drop-in for FAISS/pgvector/OpenSearch alike;
switch to it via EMBEDDING_BACKEND=rest in .env, no caller changes needed.
"""
import ssl
from typing import List

import requests
from langchain_core.embeddings import Embeddings
from requests.adapters import HTTPAdapter

from app.config import get_settings


class _SSLAdapter(HTTPAdapter):
    """Injects a custom trust store into the connection pool — needed when
    the gateway's certificate isn't in the system default CA bundle."""

    def __init__(self, cert_path: str, *args, **kwargs):
        self._ctx = ssl.create_default_context(cafile=cert_path)
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx
        return super().init_poolmanager(*args, **kwargs)


class RestEmbeddings(Embeddings):
    def __init__(self):
        s = get_settings()
        if not s.embedding_endpoint_url:
            raise ValueError("EMBEDDING_ENDPOINT_URL must be set when EMBEDDING_BACKEND=rest")

        self._url = s.embedding_endpoint_url
        self._model = s.embedding_model
        self._verify = s.embedding_cert_path or True

        self._session = requests.Session()
        if s.embedding_cert_path:
            self._session.mount("https://", _SSLAdapter(s.embedding_cert_path))
        self._headers = {"Authorization": f"Bearer {s.llm_api_key}"}

    def _embed_one(self, text: str) -> List[float]:
        response = self._session.post(
            self._url,
            json={"model": self._model, "input": text},
            headers=self._headers,
            verify=self._verify,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed_one(text)
