"""
Ingestion: load -> chunk -> embed -> upsert -> (FAISS) save to disk.

--path accepts one or more files AND/OR directories (all matching files
inside a directory are ingested, non-recursive) — e.g. drop several
guideline docx files under resources/guidelines/ and point --path at that
folder, or list files individually. All units from every resolved file are
loaded, chunked, and upserted together in one pass; each unit still carries
its own originating filename in metadata["source"] (set by the loader), so
mixing multiple docx files into the same `guidelines` index is safe and
their chunks stay distinguishable.

--path is optional for (source, index) pairs with a known default under
resources/ (see _DEFAULT_PATHS) — the API Design Guidelines docx, the
five sample OAS specs under resources/apis/, and the API Referential
sample all ship in the repo, so each of the three commands below runs with
no --path at all. Pass --path explicitly to ingest something else instead.

Usage:
  python -m app.ingestion.pipeline --source docx        --index guidelines
  python -m app.ingestion.pipeline --source oas         --index registry
  python -m app.ingestion.pipeline --source referential --index referential
  python -m app.ingestion.pipeline --source pdf         --path "./resources/security.pdf" --index guidelines

  # multiple docx files, listed explicitly:
  python -m app.ingestion.pipeline --source docx --index guidelines \\
      --path "./resources/API-Design-Guidelines.docx" "./resources/Org-API-Security-Guidelines.docx"

  # or all docx files in a directory:
  python -m app.ingestion.pipeline --source docx --index guidelines --path ./resources/guidelines/
"""
import argparse
import os
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

# Known first-party sources checked into resources/ — lets the common case
# run with no --path at all.
_DEFAULT_PATHS = {
    ("docx", "guidelines"): "./resources/API-Design-Guidelines.docx",
    ("oas", "registry"): "./resources/apis/",
    ("referential", "referential"): "./resources/api-referential.yaml",
}


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


def _tag_scopes(chunks, index_name: str) -> None:
    """Phase 2: tag guideline chunks with their scope (what OAS construct
    the rule is about), so the linker can prefer scope-matching chunks. Only
    the guidelines index — registry/referential chunks aren't guidelines.
    SCOPE_TAGGER=llm uses a chat model per chunk (richer rule-card, falls
    back to keywords on failure); default "keyword" is deterministic/free."""
    if index_name != "guidelines":
        return
    if os.environ.get("SCOPE_TAGGER", "keyword").lower() == "llm":
        from app.ingestion.llm_scope import llm_infer_scopes
        for c in chunks:
            scope, extra = llm_infer_scopes(c.metadata.get("section"), c.text)
            c.metadata["scope"] = scope
            c.metadata.update({k: v for k, v in extra.items() if v})  # applies_when, check_type
    else:
        from app.ingestion.scope_rules import infer_scopes
        for c in chunks:
            c.metadata["scope"] = infer_scopes(c.metadata.get("section"), c.text)


def run(source: str, path_args: list[str] | None, index_name: str) -> None:
    paths = _resolve_paths(source, path_args, index_name)
    loader = _LOADERS[source]

    units = []
    for path in paths:
        units.extend(loader(path))

    chunks = chunk_units(units)
    total = len(chunks)

    # Process in batches so nothing is done "all at once": each batch is
    # scope-tagged (per-chunk LLM/keyword calls), embedded, added, and
    # PERSISTED before the next batch. A failure part-way keeps every
    # already-saved batch, and the in-flight LLM/embedding calls stay bounded.
    batch_size = max(1, int(os.environ.get("INGEST_BATCH_SIZE", "25")))

    index = _INDEXES[index_name]
    store = get_vector_store(index)  # held across batches; added to, saved each batch

    if index_name == "guidelines" and os.environ.get("SCOPE_TAGGER", "keyword").lower() == "llm":
        print(f"Scope tagger: LLM ({os.environ.get('CHAT_MODEL', os.environ.get('OCR_MODEL', '?'))}) "
              f"— one call per chunk, in batches of {batch_size}")

    done = 0
    for start in range(0, total, batch_size):
        batch = chunks[start:start + batch_size]
        _tag_scopes(batch, index_name)
        store.add_documents([Document(page_content=c.text, metadata=c.metadata) for c in batch])
        save_faiss(index, store)  # persist after each batch (crash-resilient)
        done += len(batch)
        if total > batch_size:
            print(f"  ...ingested {done}/{total} chunk(s)")

    file_list = ", ".join(p.name for p in paths)
    print(f"Ingested {total} chunk(s) from {len(paths)} file(s) [{file_list}] into '{index_name}'.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=list(_LOADERS))
    ap.add_argument(
        "--path", nargs="*", default=None,
        help="One or more files and/or directories (all matching files inside a directory "
             "are ingested, non-recursive). Optional for docx/guidelines, oas/registry, and "
             "referential/referential — defaults to the matching file under resources/.",
    )
    ap.add_argument("--index", required=True, choices=list(_INDEXES))
    a = ap.parse_args()
    run(a.source, a.path, a.index)
