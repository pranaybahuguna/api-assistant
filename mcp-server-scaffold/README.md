# API Assistant — MCP Server (Phase 1 scaffold, FastMCP + FAISS)

A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes five
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
                         │   5 tools, tools/list+call     │
                         └──────┬──────────────┬─────────┘
                                │              │
                    ┌───────────┘              └───────────┐
                    ▼                                      ▼
        ┌───────────────────────┐              ┌─────────────────────────┐
        │  Spectral CLI          │              │  RAG (3 FAISS indexes)   │
        │  (resources/           │              │  Guidelines / Registry /  │
        │   api-ruleset.yaml)│              │  Referential              │
        └───────────────────────┘              └───────────┬──────────────┘
                                                             │ embeddings + OCR
                                                             ▼
                                                 ┌─────────────────────────┐
                                                 │ Internal LLM gateway      │
                                                 │ (embeddings + OCR only —  │
                                                 │  never rewrites a spec)   │
                                                 └─────────────────────────┘
```

## The five tools

| Tool | Purpose |
|---|---|
| `validate_oas` | Spectral lint + Guidelines Index retrieval (report only, does not modify the spec) |
| `fix_oas` | Same checks, reshaped into a fix plan (report only — no LLM call, no rewrite; the calling agent applies the fixes) |
| `search_api_registry` | Endpoint-level semantic search over ingested OAS specs; supports `api_id` filter |
| `search_api_referential` | API discovery — "which API do I need for X"; returns `api_id` for a follow-up registry search |
| `get_guideline_section` | Fetch a named guidelines section in full, by exact metadata match (no similarity search) |

## The validate / fix flows

**"Validate my OAS"** — one call, terminal. `validate_oas` reports; the
agent presents the findings and stops. It never fixes unless the user
separately asks. Malformed input is still a report: parser/structure
errors come back as the blocking findings, with guideline notes attached
as anticipatory context retrieved from the raw text.

**"Fix my OAS"** — the canonical sequence, in this order:

```
1. validate_oas(original)   — diagnose; show the user what's broken
2. fix_oas(original)        — get the plan (re-validates internally as a
                              stateless safety net; never fixes blind)
3. agent edits the spec     — its own LLM; zero server involvement
4. validate_oas(edited)     — confirm the findings are actually resolved
     └─ still failing? edit again — bounded: after a couple of rounds,
        report the remaining findings instead of looping
```

Diagnosis always precedes treatment; the final validation is confirmation,
not diagnosis. For malformed input there's a known two-stage effect: rule
findings are hidden behind syntax errors, so after the syntax is fixed the
next validation may surface brand-new findings — the loop handles this.
Only `validate_oas` can pronounce a spec valid; `fix_oas` has no
`is_valid` field and no rewritten-spec output, by design.

## Self-guiding tools: no reliance on a client-side system prompt

The calling agent may be a generic MCP client you don't control — no
custom instruction/system prompt telling it how these four tools relate to
each other. So that guidance can't live only in `mcp-client-scaffold`'s
agent instructions; it lives here, in two places every MCP client sees
regardless of its own prompt:

1. **Tool docstrings** (`app/main.py`) — each one states when to call it,
   what to pass, and what to do with the result (e.g.
   `search_api_referential`: "Call this FIRST... do not guess or invent an
   API"; `fix_oas`: "Call this after validate_oas reports
   is_valid=false... YOU must edit oas_content yourself"). `tools/list`
   surfaces these to any client before it ever calls a tool.
2. **A `next_step` field on every response** (`app/models.py`) — computed
   from the actual result, not static text, so it stays correct call to
   call: `validate_oas` says "call fix_oas" only when there are errors;
   `search_api_registry` warns "results span multiple APIs" only when they
   actually do; `fix_oas` spells out exactly which fields to act on.

`mcp-client-scaffold`'s agent instructions still exist and reinforce the
same workflow, but treat them as a convenience, not a dependency — a
generic agent with no custom prompt at all should still use these tools
correctly from `tools/list` + `next_step` alone. If you change how the
tools should be chained, update the docstrings/next_step logic here first;
a client-side prompt update alone won't reach a client you don't control.

### validate_oas / fix_oas — how validation actually works

Both tools check a spec against exactly two sources of truth, nothing else
(no cross-API duplicate detection, no registry lookups — the guidelines
and ruleset are the only contract). Every finding/note carries a `source`
that splits into **three** categories, not two, so the calling agent can
present them separately instead of as one flat list:

1. **`source="spectral-core"`** — generic OpenAPI best-practice findings
   from Spectral's built-in `spectral:oas` ruleset (things like
   `oas3-api-servers`, `info-contact`, `operation-operationId` — nothing
   Org-specific). No `suggested_fix`.
2. **`source="custom-ruleset"`** — Org-specific rules defined in
   `resources/api-ruleset.yaml`'s own `rules:` section (versioned
   paths, idempotency headers, etc.) — a plain YAML file consumed whole by
   the Spectral CLI (deliberately **not** vectorized — rule lookup by
   `rule_id` is an O(1) dict access, not semantic search). Each has a
   `rule_explanation` and, where the ruleset defines one, a concrete
   `suggested_fix`.
3. **`source="rag"`** — prose guidance retrieved from the Guidelines Index
   (`app/rag/retriever.py` → `retrieve_guidelines`) for rules Spectral
   can't check structurally (naming conventions, deprecation windows,
   etc.). Always `severity="info"` — informational context, never a
   pass/fail signal, since retrieval relevance isn't deterministic.

The classification between 1 and 2 is a single signal: `app/integrations/
spectral.py`'s `enrich()` checks whether a finding's `rule_id` is present
in `api-ruleset.yaml`'s own rules — if so it's `custom-ruleset`, otherwise
it's `spectral-core`. Both still come from the same `spectral lint`
subprocess call; only the finding's *label* changes.

`validate_oas` (`app/tools/validate_oas.py`) runs both and returns every
finding/note in one list; only `error`-severity findings (regardless of
whether they're `spectral-core` or `custom-ruleset`) flip `is_valid` to
`False`. The tool's docstring and `next_step` field explicitly instruct
the calling agent to present results grouped into the three categories
above rather than merging them.

`fix_oas` (`app/tools/fix_oas.py`) runs the same two checks and reshapes
the Spectral findings into `mechanical_fixes` (the ruleset defines a
concrete `suggested_fix` — apply it as stated) vs. `needs_judgment` (a
violation exists but there's no one-line fix — the caller must use
`rule_explanation` to decide), plus `guideline_notes` for prose context.
**It does not call an LLM and does not rewrite the spec.** The MCP server
only ever calls an LLM-style endpoint for embeddings and OCR — actually
fixing a spec is the calling agent's job, using its own LLM and this
tool's output as instructions. Call `validate_oas` again on the agent's
edited result to confirm the fixes actually resolved the findings.

### search_api_registry / search_api_referential

Both are thin wrappers around `retrieve_with_scores` (FAISS
`similarity_search_with_score`, L2 distance — lower score = closer match)
against one of the three indexes described below, mapping LangChain
`Document`/score pairs onto typed Pydantic hits (`RegistryHit` /
`ReferentialHit`). `search_api_registry` accepts an optional `api_id`
filter (exact-match on FAISS metadata) so an agent can first call
`search_api_referential` to find which API it needs, then narrow
`search_api_registry` to that API's endpoints only.

### Citations: every finding/hit says where it came from

- `GuidelineViolation.source_document` / `.source_section`:
  - **`source="rag"`** — from the retrieved chunk's own metadata
    (`metadata["source"]` / `metadata["section"]`, captured once at
    ingestion time in `app/ingestion/loaders.py`). `source_section` is
    `null` for guideline chunks that came from a table row, since a table
    row isn't scoped to one heading the way prose is.
  - **`source="custom-ruleset"`** — from that rule's own
    `x-guideline-section` field in `resources/api-ruleset.yaml` (e.g.
    `post-idempotency-key-header` → `"4. Idempotency"`), set in
    `app/integrations/spectral.py`'s `enrich()`. Every Org rule
    mechanically enforces exactly one guideline section, and the ruleset
    file says which one explicitly — no parsing or guessing.
  - **`source="spectral-core"`** — always `null`. Generic OpenAPI
    best-practice rules aren't tied to any Org document.
- `RegistryHit.source_document` / `ReferentialHit.source_document` — the
  OAS/inventory filename the hit came from.

This is how `validate_oas`/`fix_oas` findings (across all three sources)
and both search tools' hits can be cited back to a specific document (and
section, where applicable) rather than presented as unsourced text.

### How guideline retrieval targets the spec (guideline linking)

For a parsed spec, `guideline_context()` (`app/tools/validate_oas.py`)
delegates to `link_guidelines()` (`app/rag/guideline_linker.py`), which
links guidelines to the specific OAS elements they apply to, in two layers:

**Phase 1 — structural anchoring.** Instead of one query about the whole
spec, `extract_oas_elements()` decomposes the parsed spec into addressable
elements — the `info` block, each `(path, method)` operation, each
component schema — and builds a natural-language description of each from
its actual fields (method, path, summary, parameter names + `in`,
request-body fields, response codes). It retrieves guidelines **per
element** and anchors each hit via the finding's `path` (e.g.
`paths./orders.post`), so a note reads "this guideline applies *here*"
instead of floating in a flat list. Embeddings-only — no LLM at query time.

**Phase 2 — scope awareness.** Each guideline chunk is tagged at ingestion
with the OAS construct(s) it concerns (`response`, `header`, `security`,
`schema`, …) and stored in `metadata["scope"]`. When linking, a hit whose
scope matches the element's kind gets a soft distance boost (`SCOPE_BOOST`),
so a response-scoped guideline out-ranks a merely-text-similar one on an
operation and won't get pulled onto a schema. `"global"` scopes are a
wildcard matching every element. Soft boost, not a hard filter — robust to
imperfect tags. A `SCORE_THRESHOLD` drops the weak tail. Both constants are
embedding-model + corpus-size dependent and are tuned to the sample doc;
**re-check them on your real corpus.**

**Scope tagging — keyword (default) or LLM.** Set by `SCOPE_TAGGER`:
- `keyword` (default): deterministic heading + content keyword maps in
  `app/ingestion/scope_rules.py`. Free, no LLM.
- `llm`: one `CHAT_MODEL` call per guideline chunk
  (`app/ingestion/llm_scope.py`) extracts a richer rule-card — cleaner
  `scope` plus `applies_when` / `check_type` stored in metadata. An
  ingestion-time (offline, one-shot, cacheable) call; the live request path
  still only calls embeddings. Any LLM failure falls back to the keyword
  tagger, so ingestion never breaks. (`applies_when` is captured but not
  yet consumed at validation — evaluating it as a deterministic match
  signal is the marked next step.)

Either way it's a metadata tag, so switching taggers (or first enabling
scope at all) means re-ingesting the guidelines index.

For **malformed** input (no parse tree to walk), `guideline_context()`
skips linking and falls back to a single raw-text query over
`oas_content[:600]` — degraded but still useful, and `next_step` labels
the notes as anticipatory context rather than confirmed findings.

Additionally, every `custom-ruleset` finding carries the actual guideline
prose of the section it enforces (`guideline_excerpt`), fetched by exact
section-name match against the finding's `x-guideline-section` — no
similarity search involved. And the whole corpus is always navigable:
every validate/fix response includes `guidelines_toc` (each document's
section list, built from chunk metadata with no embedding call), and the
`get_guideline_section` tool returns any named section in full — so the
calling agent is never limited to whatever top-k retrieval surfaced.

The Spectral findings' own `rule_explanation`/`suggested_fix` are
unrelated to any of this — those come from a deterministic dict lookup by
`rule_id` against `resources/api-ruleset.yaml`'s `description`/`x-fix`
fields (`app/integrations/spectral.py`), not from vector retrieval.

### Malformed input: the parse ladder

`parse_oas()` tries the declared format first, then the other (agents get
`format` wrong; JSON is a YAML subset anyway). Three outcomes:

1. **Doesn't parse at all** → a synthetic `parse-error` finding (severity
   error) carrying the parser's own message. Spectral still runs when it
   can — but Spectral itself sometimes crashes on malformed input (exit 2,
   internal error) instead of emitting `parser` findings, so the crash is
   tolerated for input that already failed our parse and the synthetic
   finding carries the diagnosis instead. Guideline retrieval falls back
   to raw-text mode as described above.
2. **Parses but isn't an OAS** (no `openapi`/`swagger` key) → a synthetic
   `oas-structure` finding — clearer than twenty confusing lint results on
   a random config file.
3. **Valid OAS** → full pipeline.

A Spectral failure on a document that parses fine is a real server-side
problem and still raises, loudly.

### Logging: every tool call is logged twice

`app/main.py` calls `logging.basicConfig(level=logging.INFO, ...)` at
import time, so every `logger.info(...)` call anywhere in the app produces
timestamped output on stdout/stderr — check wherever the server process is
running (no separate log file or aggregation is set up; this is a POC, not
a prod logging pipeline).

Each of the four tools logs **twice** per call:
1. **On arrival**, in `app/main.py`, before anything runs — the tool name
   and raw arguments (`tools/call validate_oas: api_name=... oas_content=N
   chars`). This fires even if the tool then raises an exception.
2. **On completion**, inside `app/tools/*.py` — a summary of what was
   found/returned (e.g. `validate_oas: ... -> is_valid=False
   spectral_core=6 org_ruleset=3 guideline_notes=4 errors=2`).

Between the two, you can tell what a call was asked to do and what it
actually found without attaching a debugger.

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

Images embedded in ingested `.docx` files are read via an OpenAI-compatible
vision call (`app/ingestion/loaders.py`'s `_ocr_image`, using
`app/integrations/internal_llm.py`'s `get_ocr_model()`) — the image is
base64-encoded into a `data:` URL and sent alongside a fixed OCR prompt —
not a local `tesseract` install. This (and the optional LLM scope tagger,
`SCOPE_TAGGER=llm`) are the only LLM-style calls anywhere, and both happen
at **ingestion** — the live request path (validate/fix/search) still only
ever calls embeddings. `OCR_MODEL` selects which model on the gateway to
use for OCR. If the vision call fails (model doesn't support
images, network error), ingestion continues and just skips that image's
text with a logged warning, so a missing OCR model never blocks ingestion
of the rest of the document.

`API-Design-Guidelines.docx` ships with three embedded diagrams as a
worked example — one per section (4. Idempotency, 6. Authentication and
Authorization, 7. Rate Limiting) — each walked, OCR'd, and folded into its
section's text during ingestion the same way any of your own docx images
would be.

## Embeddings: custom REST gateway

`app/rag/embeddings.py`'s `get_embeddings()` returns a LangChain
`Embeddings` implementation that calls a custom internal gateway directly —
**one HTTP call per text** (not batched), payload shape
`{"model": ..., "input": "<single string>"}`, response parsed as
`data["data"][0]["embedding"]`, bearer auth from `LLM_API_KEY`, and an
optional custom TLS trust store (`EMBEDDING_CERT_PATH`, injected via a
`requests.adapters.HTTPAdapter` subclass that builds its own
`ssl.SSLContext` — for gateways whose certificate isn't in the system
default CA bundle). Configure the endpoint in `.env`:

```bash
EMBEDDING_ENDPOINT_URL=https://embeddings-gateway.example.com/embeddings
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_CERT_PATH=./resources/combined_trust_store.pem   # optional
```

## Vector store: FAISS

`app/rag/vector_store.py`'s `get_vector_store(index)` returns a file-based
FAISS store under `./vector_data/<index>/` — nothing else to install or
run. Every call loads straight from disk, no in-memory caching: simpler,
and it means any process always sees the latest ingested data with no
restart or cache-invalidation logic needed. `save_faiss(index, store)`
persists a store explicitly (the ingestion pipeline does this after every
`add_documents`). If no index file exists yet, a bootstrap placeholder
document is created so `similarity_search` never errors on an empty index
— `retrieve_with_scores` filters this placeholder back out.

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
  tables, three embedded diagrams) for the `guidelines` index.
- `apis/` — five sample OAS specs for the `registry` index, spanning
  different domains on purpose so semantic search has something real to
  discriminate between:

  | api_id | Domain |
  |---|---|
  | `doc-mgmt-api` | Document storage/retrieval |
  | `payments-api` | Cross-border payments |
  | `client-onboarding-api` | Client registration + KYC |
  | `fx-rates-api` | FX spot rates (read-only, no writes) |
  | `trade-settlement-api` | Securities trade settlement |
- `api-referential.yaml` — the matching inventory for all five APIs above,
  for the `referential` index (same `api_id`s link the two).

All of it is placeholder/demo content, not real Org APIs — swap it for
your own sources any time; see Quickstart below for how ingestion finds
them, and "Ingestion pipeline" above for how to point `--path` at a
directory of your own OAS files instead.

## Configuration reference (`.env`)

Every value is read straight from the environment where it's used
(`os.environ.get(...)`, with an inline default) — there's no central
settings object duplicating these across `.env` and Python.

| Variable | Default | Purpose |
|---|---|---|
| `FAISS_DIR` | `./vector_data` | Where FAISS index files are saved |
| `LLM_BASE_URL` | internal gateway URL | Chat model base URL (OpenAI-compatible) |
| `LLM_API_KEY` | `changeme` | Bearer key for chat and for the embeddings gateway |
| `OCR_MODEL` | `internal-llm` | Vision model for docx image OCR (ingestion) |
| `CHAT_MODEL` | falls back to `OCR_MODEL` | Chat model for the optional LLM scope tagger (ingestion, when `SCOPE_TAGGER=llm`) |
| `SCOPE_TAGGER` | `keyword` | Guideline scope tagging: `keyword` (deterministic, free) or `llm` (one `CHAT_MODEL` call per guideline chunk). Ingestion-time only; affects `--index guidelines` |
| `INGEST_BATCH_SIZE` | `25` | Chunks are tagged, embedded, added, and persisted this many at a time (not all at once) — crash-resilient, bounds in-flight LLM/embedding calls |
| `EMBEDDING_ENDPOINT_URL` | — | Required — the custom embeddings gateway URL |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Model name sent to the embeddings gateway |
| `EMBEDDING_CERT_PATH` | — | Optional custom CA bundle for the embeddings gateway |
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
