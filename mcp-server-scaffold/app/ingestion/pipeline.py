"""
Ingestion: load -> chunk -> embed -> upsert -> (FAISS) save to disk.

--path is optional for (source, index) pairs with a known default under
resources/ (see _DEFAULT_PATHS) — e.g. the API Design Guidelines docx
ships in the repo, so `--source docx --index guidelines` alone is enough.

Usage:
  python -m app.ingestion.pipeline --source docx        --index guidelines
  python -m app.ingestion.pipeline --source docx        --path "./sources/other-guide.docx" --index guidelines
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

# Known first-party sources checked into resources/ — lets the common case
# run with no --path at all.
_DEFAULT_PATHS = {
    ("docx", "guidelines"): "./resources/API-Design-Guidelines.docx",
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
