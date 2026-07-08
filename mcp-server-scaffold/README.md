# API Assistant — MCP Server (Phase 1 scaffold, FastMCP + FAISS)

FastMCP server exposing four tools over the real Model Context Protocol
(Streamable HTTP transport, single endpoint at `/mcp`, behind the API gateway):

| Tool | Purpose |
|---|---|
| validate_oas | Spectral lint + guideline retrieval (report only) |
| fix_oas | Same checks, returns corrected OAS + unresolved findings |
| search_api_registry | Endpoint-level semantic search; supports api_id filter |
| search_api_referential | API discovery; returns api_id for follow-up |

Tool discovery, JSON schemas, and invocation all go through the MCP protocol
itself (`tools/list`, `tools/call`) — there is no hand-rolled REST catalogue.

## Vector store: FAISS now, pgvector or OpenSearch later
POC default is FAISS saved to local files under ./vector_data — nothing to
install or run. To switch later: set VECTOR_BACKEND=pgvector (fill
VECTOR_DB_URL) or VECTOR_BACKEND=opensearch (fill OPENSEARCH_URL /
OPENSEARCH_USERNAME / OPENSEARCH_PASSWORD), and uncomment the matching deps
in requirements.txt. No other code changes — every backend is one `elif` in
`app/rag/vector_store.py`, and every caller only ever sees the LangChain
`VectorStore` interface.

## Embeddings: OpenAI-wire-compatible now, custom REST gateway later
POC default (EMBEDDING_BACKEND=openai) hits a batched OpenAI-compatible
`/embeddings` route via LLM_BASE_URL/LLM_API_KEY. If your internal gateway
speaks a different wire format instead (one text per call, a
`{"model", "input": "<string>"}` body, its own trust store), set
EMBEDDING_BACKEND=rest and fill EMBEDDING_ENDPOINT_URL (+ optionally
EMBEDDING_CERT_PATH for a custom CA bundle) — see
`app/rag/rest_embeddings.py`. Both implement LangChain's `Embeddings`
interface, so `app/rag/vector_store.py` and the ingestion pipeline never
need to change either way.

## Spectral: a file, not an index
resources/api-ruleset.yaml is consumed whole by the Spectral CLI, and
parsed once at startup into a rule_id -> {description, severity, x-fix}
dict used to enrich findings. It is deliberately not vectorized. Six rules
ship today (skip/take max, versioned paths, error-envelope $ref, POST
idempotency-key header, per-operation security, 429 Retry-After header),
each backing a "Mechanically enforced" paragraph in the guidelines doc below.

## Sample content in resources/
- `API-Design-Guidelines.docx` — a sample guidelines doc (headings,
  tables, one embedded diagram) for the `guidelines` index.
- `doc-mgmt-api.yaml` — a sample OAS spec for the `registry` index.
- `api-referential.yaml` — a sample API inventory for the `referential` index.

All three are placeholder/demo content, not real Org APIs — swap them for
your own sources any time; see Quickstart below for how ingestion finds them.

## OCR: vision LLM, not a local binary
Images embedded in ingested .docx files are read via the same
OpenAI-compatible chat model `fix_oas` uses (a multimodal call), not a
local `tesseract` install — one less system dependency, and no separate
OCR pipeline to keep in sync with the LLM client config.

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

`FASTMCP_CHECK_FOR_UPDATES=off` in `.env.example` disables FastMCP's startup
version-check network call — this server runs on an internal, likely
egress-restricted network.
