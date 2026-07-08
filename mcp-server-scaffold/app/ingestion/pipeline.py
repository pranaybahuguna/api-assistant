"""
Ingestion: load -> chunk -> embed -> upsert -> (FAISS) save to disk.

Usage:
  python -m app.ingestion.pipeline --source docx        --path "./sources/API+Design+Guide.docx"      --index guidelines
  python -m app.ingestion.pipeline --source pdf         --path "./sources/security.pdf"               --index guidelines
  python -m app.ingestion.pipeline --source oas         --path "./sources/doc-mgmt-api.yaml"          --index registry
  python -m app.ingestion.pipeline --source referential --path "./sources/api-referential.yaml"       --index referential
"""
import argparse
from pathlib import Path

from langchain_core.documents import Document

from app.ingestion.loaders import load_docx, load_pdf, load_oas, load_referential
from app.ingestion.chunkers import chunk_units
from app.rag.vector_store import Index, get_vector_store, save_faiss

_LOADERS = {"docx": load_docx, "pdf": load_pdf, "oas": load_oas, "referential": load_referential}
_INDEXES = {"guidelines": Index.GUIDELINES, "registry": Index.REGISTRY, "referential": Index.REFERENTIAL}


def run(source: str, path: str, index_name: str) -> None:
    units = _LOADERS[source](Path(path))
    chunks = chunk_units(units)
    docs = [Document(page_content=c.text, metadata=c.metadata) for c in chunks]

    index = _INDEXES[index_name]
    get_vector_store(index).add_documents(docs)
    save_faiss(index)  # persist to ./vector_data/<index>/ (no-op for pgvector)

    print(f"Ingested {len(docs)} chunk(s) from {path} into '{index_name}'.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=list(_LOADERS))
    ap.add_argument("--path", required=True)
    ap.add_argument("--index", required=True, choices=list(_INDEXES))
    a = ap.parse_args()
    run(a.source, a.path, a.index)
