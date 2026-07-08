from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Vector store backend: "faiss" (file-based, POC) or "pgvector" (later) ---
    vector_backend: str = "faiss"
    faiss_dir: str = "./vector_data"          # where FAISS index files are saved
    vector_db_url: str = ""                    # only needed when vector_backend=pgvector

    # --- Internal Org-hosted LLM (OpenAI-compatible gateway) ---
    llm_base_url: str = "https://llm-gateway.example.com/v1"
    llm_api_key: str = "changeme"
    embedding_model: str = "text-embedding-3-large"
    chat_model: str = "internal-llm"

    # --- Spectral (plain file on the server — NOT vectorized) ---
    spectral_ruleset_path: str = "./resources/api-ruleset.yaml"
    spectral_binary: str = "spectral"


@lru_cache
def get_settings() -> Settings:
    return Settings()
