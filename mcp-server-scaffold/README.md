# API Assistant — MCP Server (Phase 1 scaffold, FastMCP + FAISS)

A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes four
tools over the real Model Context Protocol (Streamable HTTP transport,
single endpoint at `/mcp`, sitting behind the API gateway in prod). Any MCP-aware
client — the companion `mcp-client-scaffold` (Google ADK) or the API Assistant
directly — gets tool discovery, JSON schemas, and invocation straight from
the protocol (`tools/list`, `tools/call`); there is no hand-rolled REST
catalogue to keep in sync.

```
                         ┌─────────────────────────────┐
                         │   MCP client (ADK agent /    │
                         │   any MCP-aware caller)       │
                         └──────────────┬────────────────┘
                                        │ Streamable HTTP  (POST/GET /mcp)
                                        ▼
                         ┌─────────────────────────────┐
                         │   FastMCP server (app/main.py)│
                         │   4 tools, tools/list+call     │
                         └──────┬──────────────┬─────────┘
                                │              │
                    ┌───────────┘              └───────────┐
                    ▼                                      ▼
        ┌───────────────────────┐              ┌─────────────────────────┐
        │  Spectral CLI          │              │  RAG (3 FAISS indexes)   │
        │  (resources/           │              │  Guidelines / Registry /  │
        │   api-ruleset.yaml)│              │  Referential              │
        └───────────────────────┘              └───────────┬──────────────┘
                                                             │ embeddings
                                                             ▼
                                                 ┌─────────────────────────┐
                                                 │ Internal LLM gateway      │
                                                 │ (chat + embeddings)       │
                                                 └─────────────────────────┘
```

## The four tools

| Tool | Purpose |
|---|---|
| `validate_oas` | Spectral lint + Guidelines Index retrieval (report only, does not modify the spec) |
| `fix_oas` | Same checks, then an LLM rewrite; returns the corrected spec + unresolved findings |
| `search_api_registry` | Endpoint-level semantic search over ingested OAS specs; supports `api_id` filter |
| `search_api_referential` | API discovery — "which API do I need for X"; returns `api_id` for a follow-up registry search |

### validate_oas / fix_oas — how validation actually works

Both tools check a spec against exactly two sources of truth, nothing else
(no cross-API duplicate detection, no registry lookups — the guidelines
and ruleset are the only contract):

1. **Spectral lint** (`app/integrations/spectral.py`) — runs the Spectral
   CLI as a subprocess against `resources/api-ruleset.yaml`, a plain
   YAML file consumed whole (deliberately **not** vectorized — rule
   lookup by `rule_id` is an O(1) dict access, not semantic search). Every
   finding Spectral returns is enriched with that rule's `description` and
   `x-fix` remediation text from the same file. This is the only source
   that affects `is_valid` in `validate_oas` — it's deterministic pass/fail.
2. **Guidelines Index retrieval** (`app/rag/retriever.py` →
   `retrieve_guidelines`) — a RAG lookup over the ingested
   `API-Design-Guidelines.docx` for prose rules Spectral can't check
   structurally (naming conventions, deprecation windows, etc.). Always
   surfaced as `severity="info", source="rag"` — informational context,
   never a pass/fail signal, since retrieval relevance isn't deterministic.

`validate_oas` (`app/tools/validate_oas.py`) runs both and returns every
finding/note in one list; only Spectral `error`-severity findings flip
`is_valid` to `False`.

`fix_oas` (`app/tools/fix_oas.py`) runs the same two checks independently
(fresh Spectral run + guideline context), feeds both into a prompt asking
the internal LLM to rewrite the spec ("change only what a finding or
guideline requires; don't break existing consumers"), parses the model's
JSON response (`{"fixed_oas": "...", "changes": [...]}`, tolerating stray
markdown fences), then **re-runs Spectral on its own output** so
`unresolved_violations` reflects what's actually still wrong in the fixed
spec — not what the model claims to have fixed.

### search_api_registry / search_api_referential

Both are thin wrappers around `retrieve_with_scores` (FAISS
`similarity_search_with_score`, L2 distance — lower score = closer match)
against one of the three indexes described below, mapping LangChain
`Document`/score pairs onto typed Pydantic hits (`RegistryHit` /
`ReferentialHit`). `search_api_registry` accepts an optional `api_id`
filter (exact-match on FAISS metadata) so an agent can first call
`search_api_referential` to find which API it needs, then narrow
`search_api_registry` to that API's endpoints only.

## RAG pipeline: three indexes, linked by api_id

Three separate FAISS stores under `./vector_data/<index>/`, each backing
one tool's retrieval:

| Index | Source | Chunk granularity | Tool(s) |
|---|---|---|---|
| `guidelines` | `API-Design-Guidelines.docx` | one chunk per headed section (sliding window if long) + one per table row + OCR'd image text folded into its section | `validate_oas`, `fix_oas` |
| `registry` | OAS specs (e.g. `doc-mgmt-api.yaml`) | one chunk per `(path, method)` operation + one spec-summary chunk per API | `search_api_registry` |
| `referential` | API inventory (e.g. `api-referential.yaml`) | one chunk per API entry (already atomic, no splitting) | `search_api_referential` |

`registry` and `referential` chunks both carry the same `api_id` in their
FAISS metadata — the link that lets an agent call
`search_api_referential("store client documents")` → get back
`api_id: doc-mgmt-api` → call `search_api_registry(query=..., api_id="doc-mgmt-api")`
to see only that API's endpoints.

### Ingestion pipeline (`app/ingestion/`)

`load -> chunk -> embed -> upsert -> save`, one command per source/index
pair:

```bash
python -m app.ingestion.pipeline --source docx        --index guidelines
python -m app.ingestion.pipeline --source oas         --index registry
python -m app.ingestion.pipeline --source referential --index referential
```

- **`loaders.py`** — format-aware, returns `RawUnit`s (the smallest piece
  worth treating separately):
  - `load_docx` — walks paragraphs, starts a new unit at each `Heading*`
    style, flattens tables into one `"Header: value. Header: value."`
    sentence per row, and OCRs any inline image via the vision-capable
    chat model (see below), appending the extracted text into whichever
    section the image sits in (an image illustrates the rule around it,
    so it must not float as its own untethered chunk).
  - `load_oas` — one `RawUnit` per `(path, method)` operation (summary +
    description + flattened parameter list) plus one spec-summary unit
    listing every endpoint; every unit gets the same `api_id` (defaults to
    the filename stem) and `api_name` (from `info.title`).
  - `load_referential` — one `RawUnit` per inventory entry, no splitting.
  - `load_pdf` — one unit per page (for guideline sources shipped as PDF
    instead of docx).
- **`chunkers.py`** — prose units get a sliding-window split
  (`RecursiveCharacterTextSplitter`, ~700-word window / ~100-word overlap);
  every other unit type (`table_row`, `oas_operation`, `oas_summary`,
  `referential_entry`) is already atomic and passes through unchanged.
- **`pipeline.py`** — wires loader → chunker → `get_vector_store(index)` →
  `add_documents` → `save_faiss`. `--path` is optional for the three
  first-party sources (`_DEFAULT_PATHS` maps them to their file under
  `resources/`); pass `--path` explicitly to ingest something else (a PDF,
  your own OAS/referential source).

  `--path` also accepts **multiple files and/or directories** in one run —
  every matching-extension file inside a given directory is picked up
  (non-recursive) — so several guideline docx files can be ingested into
  the same `guidelines` index together:

  ```bash
  # explicit list
  python -m app.ingestion.pipeline --source docx --index guidelines \
      --path "./resources/API-Design-Guidelines.docx" "./resources/Org-API-Security-Guidelines.docx"

  # or everything in a folder
  python -m app.ingestion.pipeline --source docx --index guidelines --path ./resources/guidelines/
  ```

  All resolved files' units are loaded and chunked together in one pass;
  each chunk still carries its own originating filename in
  `metadata["source"]` (set by the loader), so chunks from different docx
  files stay distinguishable even after landing in the same index.

### OCR: vision LLM, not a local binary

Images embedded in ingested `.docx` files are read via the same
OpenAI-compatible chat model `fix_oas` uses (a multimodal call — the image
is base64-encoded into a `data:` URL and sent alongside a fixed OCR
prompt), not a local `tesseract` install. One less system dependency, and
no separate OCR pipeline to keep in sync with the LLM client config. If the
vision call fails (model doesn't support images, network error), ingestion
continues and just skips that image's text with a logged warning.

## Pluggable embeddings: OpenAI-wire-compatible now, custom REST gateway later

`app/rag/embeddings.py` is a factory, `get_embeddings()`, branching on
`EMBEDDING_BACKEND`:

- **`openai`** (default) — `langchain_openai.OpenAIEmbeddings` against a
  batched, OpenAI-wire-compatible `/embeddings` route via
  `LLM_BASE_URL`/`LLM_API_KEY`.
- **`rest`** — `app/rag/rest_embeddings.py`'s `RestEmbeddings`, for
  internal gateways that speak a different wire format entirely: **one
  HTTP call per text** (not batched), payload shape
  `{"model": ..., "input": "<single string>"}`, response parsed as
  `data["data"][0]["embedding"]`, bearer auth from `LLM_API_KEY`, and an
  optional custom TLS trust store (`EMBEDDING_CERT_PATH`, injected via a
  `requests.adapters.HTTPAdapter` subclass that builds its own
  `ssl.SSLContext` — for gateways whose certificate isn't in the system
  default CA bundle).

Both implement LangChain's `Embeddings` interface
(`embed_documents`/`embed_query`), so nothing downstream — `vector_store.py`,
the ingestion pipeline, any tool — needs to know or care which one is
active. Switching is a `.env` change only:

```bash
EMBEDDING_BACKEND=rest
EMBEDDING_ENDPOINT_URL=https://embeddings-gateway.example.com/embeddings
EMBEDDING_CERT_PATH=./resources/combined_trust_store.pem   # optional
```

## Pluggable vector store: FAISS now, pgvector or OpenSearch later

`app/rag/vector_store.py`'s `get_vector_store(index)` is a factory
branching on `VECTOR_BACKEND`, one `elif` per backend:

- **`faiss`** (default, POC) — file-based, saved under
  `./vector_data/<index>/`. Nothing to install or run. FAISS is in-memory
  until `save_faiss(index)` is called explicitly (the ingestion pipeline
  does this after every `add_documents`); a process-local cache
  (`_faiss_cache`) avoids re-loading from disk on every call within the
  same process. If no index file exists yet, a bootstrap placeholder
  document is created so `similarity_search` never errors on an empty
  index — `retrieve_with_scores` filters this placeholder back out.
- **`pgvector`** — `langchain_postgres.PGVector`, deferred-imported so the
  POC doesn't need `psycopg` installed unless this backend is actually
  selected. Needs `VECTOR_DB_URL`.
- **`opensearch`** — `langchain_community.vectorstores.OpenSearchVectorSearch`,
  same deferred-import pattern. Needs `OPENSEARCH_URL` (+ optionally
  `OPENSEARCH_USERNAME`/`OPENSEARCH_PASSWORD`/`OPENSEARCH_VERIFY_CERTS`).

Every caller only ever sees LangChain's `VectorStore` interface
(`similarity_search_with_score`, `add_documents`), so swapping backends —
including combining it with either embeddings backend above — never
touches `app/tools/*.py`, `app/rag/retriever.py`, or the ingestion
pipeline. Add a fourth backend by adding one more `elif` branch here.

## Spectral: a file, not an index

`resources/api-ruleset.yaml` is consumed whole by the Spectral CLI as
a subprocess (`spectral lint <tmpfile> --ruleset <path> --format json`),
and parsed once at startup (`lru_cache`) into a
`rule_id -> {description, severity, x-fix}` dict used to enrich findings —
deliberately not vectorized, since a finding already carries its exact
`rule_id`, making enrichment an O(1) lookup rather than a semantic search.
Six rules ship today:

| Rule | Section |
|---|---|
| `skip-take-maximum` | Pagination — skip/take must define a `maximum` |
| `versioned-path-required` | Versioning — every path starts with `/v{n}/` |
| `error-envelope-ref` | Error Handling — 4xx/5xx must `$ref` the shared `ErrorEnvelope` schema |
| `post-idempotency-key-header` | Idempotency — POSTs that create a resource need a required `Idempotency-Key` header |
| `operation-security-required` | Authentication — every operation needs a security requirement |
| `rate-limited-retry-after` | Rate Limiting — 429 responses need a `Retry-After` header |

Each backs a "Mechanically enforced" paragraph in
`API-Design-Guidelines.docx`; everything else in that doc is prose-only
guidance retrieved via the Guidelines Index instead, since Spectral can't
check it structurally (see `npm install -g @stoplight/spectral-cli` in
Quickstart — the CLI is the rule *engine*, this YAML is just its
configuration; you need both).

## Sample content in resources/

- `API-Design-Guidelines.docx` — a sample guidelines doc (headings,
  tables, one embedded diagram) for the `guidelines` index.
- `doc-mgmt-api.yaml` — a sample OAS spec for the `registry` index.
- `api-referential.yaml` — a sample API inventory for the `referential` index.

All three are placeholder/demo content, not real Org APIs — swap them for
your own sources any time; see Quickstart below for how ingestion finds them.

## Configuration reference (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `VECTOR_BACKEND` | `faiss` | `faiss` \| `pgvector` \| `opensearch` |
| `FAISS_DIR` | `./vector_data` | Where FAISS index files are saved |
| `VECTOR_DB_URL` | — | Postgres DSN, only when `VECTOR_BACKEND=pgvector` |
| `OPENSEARCH_URL` / `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` / `OPENSEARCH_VERIFY_CERTS` | — | Only when `VECTOR_BACKEND=opensearch` |
| `LLM_BASE_URL` | internal gateway URL | Chat model base URL (OpenAI-compatible) |
| `LLM_API_KEY` | `changeme` | Bearer key for chat, and for the `rest` embeddings backend |
| `CHAT_MODEL` | `internal-llm` | Model name used by `fix_oas` and image OCR |
| `EMBEDDING_BACKEND` | `openai` | `openai` \| `rest` |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Model name sent to whichever embeddings backend is active |
| `EMBEDDING_ENDPOINT_URL` | — | Only when `EMBEDDING_BACKEND=rest` |
| `EMBEDDING_CERT_PATH` | — | Optional custom CA bundle, only for the `rest` backend |
| `SPECTRAL_RULESET_PATH` | `./resources/api-ruleset.yaml` | Ruleset file passed to the Spectral CLI |
| `SPECTRAL_BINARY` | `spectral` | Spectral CLI binary name/path |
| `FASTMCP_CHECK_FOR_UPDATES` | `off` | Disables FastMCP's startup version-check network call (internal, egress-restricted network) |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install -g @stoplight/spectral-cli     # the linter binary
cp .env.example .env                        # fill in your internal LLM URL/key

# Ingest the knowledge base (FAISS files land in ./vector_data).
# --path is optional for these three — they default to the matching file
# under resources/. Pass --path to ingest a different file instead.
python -m app.ingestion.pipeline --source docx        --index guidelines
python -m app.ingestion.pipeline --source oas         --index registry
python -m app.ingestion.pipeline --source referential --index referential

python -m app.main                          # local dev, or:
uvicorn app.main:app --port 8080            # prod (same `app` object either way)
```

Verify the server is up and discoverable over MCP:

```bash
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
# grab the mcp-session-id response header, then:
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <id from above>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

## The client side

`../mcp-client-scaffold` is a Google ADK agent (`LlmAgent` + `LiteLlm` +
`McpToolset`) that connects to this server over Streamable HTTP and
discovers all four tools live from `tools/list` — nothing about them is
hand-wired on the client. See that project's own README for setup; in
short, it needs its own internal LLM credentials (for the agent's
reasoning) plus this server's URL (`API_ASSISTANT_MCP_URL`).
