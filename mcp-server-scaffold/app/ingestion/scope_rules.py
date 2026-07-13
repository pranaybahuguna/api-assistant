"""
Scope tagging for guideline chunks (Phase 2 of guideline linking).

Each guideline chunk is tagged with one or more "scopes" — what part of an
OpenAPI spec the rule is about — so the linker can prefer chunks whose
scope matches the OAS element it's examining (a response-scoped guideline
shouldn't get pulled onto a schema).

Deterministic: a heading map (coarse) unioned with a content keyword scan
(fine). No LLM. Everything here is meant to be eyeballed and tuned against
your actual guidelines doc — see dump via link_guidelines' scope report.

Scope vocabulary (mirrors OAS structure):
    global        applies broadly / API-wide (naming philosophy, change mgmt)
    path          URL / endpoint structure (versioning, path casing)
    operation     per-operation behaviour (idempotency, method semantics)
    query-param   query parameters (pagination, filtering)
    header        request/response headers (x-request-id, deprecation)
    request-body  request payload conventions
    response      status codes, error envelopes, response structure
    schema        component/model field naming and types
    security      auth, scopes, tokens

"global" is a wildcard: a chunk scoped "global" is considered relevant to
every element (see linker). A chunk that matches nothing falls back to
{"global"} so it is never silently excluded.
"""

SCOPES = {
    "global", "path", "operation", "query-param", "header",
    "request-body", "response", "schema", "security",
}

# Coarse: substring in the section heading -> scopes. Calibrated to the
# sample API-Design-Guidelines.docx headings; extend for your doc.
_HEADING_SCOPES: list[tuple[str, set[str]]] = [
    ("naming", {"path", "schema", "query-param"}),
    ("resource", {"path"}),
    ("pagination", {"query-param", "operation"}),
    ("error", {"response"}),
    ("idempotency", {"operation", "header"}),
    ("versioning", {"path", "header"}),
    ("deprecation", {"header", "path"}),
    ("authentication", {"security", "operation"}),
    ("authorization", {"security", "operation"}),
    ("rate limit", {"response", "header"}),
    ("documenting", {"global"}),
]

# Fine: substring in the chunk text -> scopes. Reinforces/covers headings
# that don't match the coarse map (e.g. an arbitrary guidelines doc).
_CONTENT_SCOPES: list[tuple[str, set[str]]] = [
    ("header", {"header"}),
    ("endpoint", {"path"}),
    ("/v", {"path"}),
    ("path segment", {"path"}),
    ("kebab-case", {"path"}),
    ("spinal-case", {"path"}),
    ("query parameter", {"query-param"}),
    ("skip", {"query-param"}),
    ("take", {"query-param"}),
    ("limit", {"query-param"}),
    ("offset", {"query-param"}),
    ("pagination", {"query-param"}),
    ("status code", {"response"}),
    ("4xx", {"response"}),
    ("5xx", {"response"}),
    ("429", {"response", "header"}),
    ("retry-after", {"response", "header"}),
    ("error envelope", {"response"}),
    ("errorenvelope", {"response"}),
    ("request body", {"request-body"}),
    ("property", {"schema"}),
    ("properties", {"schema"}),
    ("attribute", {"schema"}),
    ("field", {"schema"}),
    ("camelcase", {"schema"}),
    ("lowercamelcase", {"schema"}),
    ("oauth", {"security"}),
    ("token", {"security"}),
    ("scope", {"security"}),
    ("bearer", {"security"}),
    ("authenticat", {"security"}),
    ("authoriz", {"security"}),
    ("idempoten", {"operation", "header"}),
    ("post", {"operation"}),
    ("versioned", {"path"}),
    ("deprecat", {"header"}),
]


def infer_scopes(section: str | None, text: str) -> list[str]:
    """Union of heading-tier and content-tier scope matches. Falls back to
    {"global"} when nothing matches, so a chunk is never left un-scoped."""
    found: set[str] = set()
    heading = (section or "").lower()
    body = (text or "").lower()

    for needle, scopes in _HEADING_SCOPES:
        if needle in heading:
            found |= scopes
    for needle, scopes in _CONTENT_SCOPES:
        if needle in body:
            found |= scopes

    return sorted(found) if found else ["global"]
