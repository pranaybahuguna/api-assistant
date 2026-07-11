"""
Embeddings client for the internal LLM gateway — one HTTP call per text,
{"model", "input": "<string>"} payload, bearer auth, optional custom TLS
trust store for gateways whose cert isn't in the system CA bundle.
"""
import os
import ssl
from typing import List

import requests
from langchain_core.embeddings import Embeddings
from requests.adapters import HTTPAdapter


class _SSLAdapter(HTTPAdapter):
    def __init__(self, cert_path: str, *args, **kwargs):
        self._ctx = ssl.create_default_context(cafile=cert_path)
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx
        return super().init_poolmanager(*args, **kwargs)


class _RestEmbeddings(Embeddings):
    def __init__(self):
        self._url = os.environ["EMBEDDING_ENDPOINT_URL"]
        self._model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")

        cert_path = os.environ.get("EMBEDDING_CERT_PATH", "")
        self._verify = cert_path or True
        self._session = requests.Session()
        if cert_path:
            self._session.mount("https://", _SSLAdapter(cert_path))
        self._headers = {"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'changeme')}"}

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


def get_embeddings() -> Embeddings:
    return _RestEmbeddings()
