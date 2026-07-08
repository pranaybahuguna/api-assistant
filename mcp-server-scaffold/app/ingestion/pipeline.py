"""
Ingestion: load -> chunk -> embed -> upsert -> (FAISS) save to disk.

--path is optional for (source, index) pairs with a known default under
resources/ (see _DEFAULT_PATHS) — the API Design Guidelines docx, the
doc-mgmt-api OAS sample, and the API Referential sample all ship in the
repo under resources/, so each of the four commands below runs with no
--path at all. Pass --path explicitly to ingest a different file instead
(e.g. a PDF, or your own OAS/referential source).

Usage:
  python -m app.ingestion.pipeline --source docx        --index guidelines
  python -m app.ingestion.pipeline --source oas         --index registry
  python -m app.ingestion.pipeline --source referential --index referential
  python -m app.ingestion.pipeline --source pdf         --path "./resources/security.pdf" --index guidelines
"""
import argparse
from pathlib import Path

from langchain_core.documents import Document

from app.ingestion.loaders import load_docx, load_pdf, load_oas, load_referential
from app.ingestion.chunkers import chunk_units
from app.rag.vector_store import Index, get_vector_store, save_faiss

_LOADERS = {"docx": load_docx, "pdf": load_pdf, "oas": load_oas, "referential": load_referential}
_INDEXES = {"guidelines": Index.GUIDELINES, "registry": Index.REGISTRY, "referential": Index.REFERENTIAL}

# Known first-party sources checked into resources/ — lets the common case
# run with no --path at all.
_DEFAULT_PATHS = {
    ("docx", "guidelines"): "./resources/API-Design-Guidelines.docx",
    ("oas", "registry"): "./resources/doc-mgmt-api.yaml",
    ("referential", "referential"): "./resources/api-referential.yaml",
}


def run(source: str, path: str | None, index_name: str) -> None:
    path = path or _DEFAULT_PATHS.get((source, index_name))
    if not path:
        raise SystemExit(
            f"--path is required for --source {source} --index {index_name} "
            f"(no default registered in _DEFAULT_PATHS)"
        )

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
    ap.add_argument("--path", default=None)
    ap.add_argument("--index", required=True, choices=list(_INDEXES))
    a = ap.parse_args()
    run(a.source, a.path, a.index)
