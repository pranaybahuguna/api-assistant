from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Vector store backend: "faiss" (file-based, POC) | "pgvector" | "opensearch" ---
    vector_backend: str = "faiss"
    faiss_dir: str = "./vector_data"          # where FAISS index files are saved
    vector_db_url: str = ""                    # only needed when vector_backend=pgvector

    # --- OpenSearch (only needed when vector_backend=opensearch) ---
    opensearch_url: str = ""
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_verify_certs: bool = True

    # --- Internal Org-hosted LLM (chat) ---
    llm_base_url: str = "https://llm-gateway.example.com/v1"
    llm_api_key: str = "changeme"
    chat_model: str = "internal-llm"

    # --- Embeddings: "openai" (OpenAI-wire-compatible /embeddings, batched) or
    # "rest" (custom internal gateway — one text per call, different payload
    # shape, optional custom trust store). See app/rag/embeddings.py. ---
    embedding_backend: str = "openai"
    embedding_model: str = "text-embedding-3-large"
    embedding_endpoint_url: str = ""           # only needed when embedding_backend=rest
    embedding_cert_path: str = ""              # optional custom CA bundle for the rest backend

    # --- Spectral (plain file on the server — NOT vectorized) ---
    spectral_ruleset_path: str = "./resources/api-ruleset.yaml"
    spectral_binary: str = "spectral"


@lru_cache
def get_settings() -> Settings:
    return Settings()
