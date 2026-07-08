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

## Vector store: FAISS now, pgvector later
POC default is FAISS saved to local files under ./vector_data — nothing to
install or run. To switch later: set VECTOR_BACKEND=pgvector and
VECTOR_DB_URL in .env, uncomment the two pgvector deps in requirements.txt.
No other code changes — everything goes through app/rag/vector_store.py.

## Spectral: a file, not an index
resources/api-ruleset.yaml is consumed whole by the Spectral CLI, and
parsed once at startup into a rule_id -> {description, severity, x-fix}
dict used to enrich findings. It is deliberately not vectorized.

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install -g @stoplight/spectral-cli     # the linter binary
# apt install tesseract-ocr                # optional, for image OCR
cp .env.example .env                        # fill in your internal LLM URL/key

# Ingest the knowledge base (FAISS files land in ./vector_data)
python -m app.ingestion.pipeline --source docx --path "./sources/API+Design+Guide.docx" --index guidelines
python -m app.ingestion.pipeline --source docx --path "./sources/API Design Guidelines.docx" --index guidelines
python -m app.ingestion.pipeline --source oas  --path "./sources/doc-mgmt-api.yaml" --index registry
python -m app.ingestion.pipeline --source referential --path "./sources/api-referential.yaml" --index referential

python -m app.main                          # local dev, or:
uvicorn app.main:app --port 8080            # prod (same `app` object either way)
```

`FASTMCP_CHECK_FOR_UPDATES=off` in `.env.example` disables FastMCP's startup
version-check network call — this server runs on an internal, likely
egress-restricted network.
