"""
Ingestion: load -> chunk -> embed -> upsert -> (FAISS) save to disk.

--path accepts one or more files AND/OR directories (all matching files
inside a directory are ingested, non-recursive) — e.g. drop several
guideline docx files in a local folder and point --path at it, or list
files individually. All units from every resolved file are loaded,
chunked, and upserted together in one pass; each unit still carries its
own originating filename in metadata["source"] (set by the loader), so
mixing multiple docx files into the same `guidelines` index is safe and
their chunks stay distinguishable.

--path is REQUIRED: no resource files ship with this repo (the guidelines
doc, OAS specs, and referential inventory are deployment-time assets you
supply locally). Register your own defaults in _DEFAULT_PATHS if you want
to omit --path for common cases.

Usage:
  python -m app.ingestion.pipeline --source docx        --path ./API-Design-Guidelines.docx --index guidelines
  python -m app.ingestion.pipeline --source oas         --path ./apis/ --index registry
  python -m app.ingestion.pipeline --source referential --path ./api-referential.yaml --index referential
  python -m app.ingestion.pipeline --source pdf         --path ./security.pdf --index guidelines
"""
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from langchain_core.documents import Document

from app.ingestion.loaders import load_docx, load_pdf, load_oas, load_referential
from app.ingestion.chunkers import chunk_units
from app.rag.vector_store import Index, get_vector_store, save_faiss

_LOADERS = {"docx": load_docx, "pdf": load_pdf, "oas": load_oas, "referential": load_referential}
_INDEXES = {"guidelines": Index.GUIDELINES, "registry": Index.REGISTRY, "referential": Index.REFERENTIAL}

# Extensions recognized when --path points at a directory.
_EXTENSIONS = {
    "docx": (".docx",),
    "pdf": (".pdf",),
    "oas": (".yaml", ".yml", ".json"),
    "referential": (".yaml", ".yml", ".json"),
}

# No bundled sources ship with this repo — resource files (guidelines doc,
# OAS specs, referential inventory) are deployment-time assets. Always pass
# --path, or register your own local defaults here.
_DEFAULT_PATHS: dict = {}


def _resolve_paths(source: str, path_args: list[str] | None, index_name: str) -> list[Path]:
    """Expand --path into a flat, sorted list of files. Each entry may be a
    single file or a directory (every matching-extension file directly
    inside it, non-recursive). Falls back to the registered default when
    --path is omitted entirely."""
    raw = path_args or (
        [_DEFAULT_PATHS[(source, index_name)]] if (source, index_name) in _DEFAULT_PATHS else None
    )
    if not raw:
        raise SystemExit(
            f"--path is required for --source {source} --index {index_name} "
            f"(no default registered in _DEFAULT_PATHS)"
        )

    exts = _EXTENSIONS[source]
    resolved: list[Path] = []
    for entry in raw:
        p = Path(entry)
        if p.is_dir():
            matches = sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts)
            if not matches:
                raise SystemExit(f"No {'/'.join(exts)} files found in directory {p}")
            resolved.extend(matches)
        elif p.exists():
            resolved.append(p)
        else:
            raise SystemExit(f"Path not found: {p}")
    return resolved


def run(source: str, path_args: list[str] | None, index_name: str) -> None:
    paths = _resolve_paths(source, path_args, index_name)
    loader = _LOADERS[source]

    units = []
    for path in paths:
        units.extend(loader(path))

    chunks = chunk_units(units)
    docs = [Document(page_content=c.text, metadata=c.metadata) for c in chunks]

    index = _INDEXES[index_name]
    store = get_vector_store(index)
    store.add_documents(docs)
    save_faiss(index, store)  # persist to ./vector_data/<index>/

    file_list = ", ".join(p.name for p in paths)
    print(f"Ingested {len(docs)} chunk(s) from {len(paths)} file(s) [{file_list}] into '{index_name}'.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=list(_LOADERS))
    ap.add_argument(
        "--path", nargs="*", default=None,
        help="One or more files and/or directories (all matching files inside a directory "
             "are ingested, non-recursive). Optional for docx/guidelines, oas/registry, and "
             "referential/referential — defaults to the matching file registered in _DEFAULT_PATHS (none ship with this repo).",
    )
    ap.add_argument("--index", required=True, choices=list(_INDEXES))
    a = ap.parse_args()
    run(a.source, a.path, a.index)
