"""
Guideline linker.

Phase 1 — structural anchoring: the old approach ran a few whole-spec
queries and returned a flat list of guideline notes with no sense of WHERE
in the OAS each one applied. This inverts it: decompose the spec into
addressable elements (the info block, each operation, each schema),
retrieve guidelines per element, and anchor each hit to the element's
location so a note reads "this guideline applies to paths./items.post"
instead of floating unattached.

Phase 2 — scope awareness: each guideline chunk is tagged at ingestion
with the OAS construct(s) it concerns (app/ingestion/scope_rules.py). When
linking, a hit whose scope matches the element's kind gets a soft distance
boost (SCOPE_BOOST), so a response-scoped guideline out-ranks a
merely-text-similar one on an operation and won't get pulled onto a
schema. Soft boost, not a hard filter — robust to imperfect scope tags.

Only embeddings are used (via retrieve_with_scores) — no LLM calls, in
keeping with the server's embeddings+OCR-only constraint.

Cost note: this issues one retrieval per element (an embedding call each),
so a 15-element spec costs ~15 embedding calls per validate — more than
the old ~7 fixed queries, traded for per-location precision. Tune
K_PER_ELEMENT / MAX_NOTES / SCORE_THRESHOLD to balance.
"""
from dataclasses import dataclass

from app.models import GuidelineViolation
from app.rag.retriever import retrieve_with_scores
from app.rag.vector_store import Index

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# Retrieval knobs. SCORE_THRESHOLD is an L2 distance ceiling (lower = closer);
# guideline hits farther than this are dropped as not-really-relevant. None
# disables the cutoff. The right value depends on the embedding model and
# needs a real-embeddings run to tune — left lenient/off by default so mock
# runs still return something.
K_PER_ELEMENT = 2
MAX_NOTES = 8
# Tuned against text-embedding-3-small on the sample guidelines doc: real
# match distances cluster ~1.25-1.55, so 1.5 trims the clear tail without
# emptying any element. RE-CHECK on the real (larger) guidelines corpus —
# distance ranges shift with corpus size and embedding model.
SCORE_THRESHOLD: float | None = 1.5

# Phase 2: subtracted from a hit's distance when its scope matches the
# element being examined, so scope-aligned guidelines rank higher (soft
# boost, not a hard filter — robust to imperfect scope tags). Tuned to 0.1:
# adjacent hits differ by ~0.05, so 0.1 reorders near-ties toward scope
# matches without steamrolling a genuinely-closer non-matching hit (0.3
# did, effectively becoming a hard filter). L2-distance units — re-check
# on the real corpus.
SCOPE_BOOST = 0.1

# Which guideline scopes are relevant to each kind of OAS element. A chunk
# scoped "global" matches every element (wildcard, handled in _scope_match).
_ELEMENT_SCOPES: dict[str, set[str]] = {
    "info": set(),  # only "global" chunks boost onto info
    "operation": {"operation", "query-param", "header", "request-body", "response", "security"},
    "schema": {"schema", "request-body", "response"},
}


def _scope_match(chunk_scopes, element_kind: str) -> bool:
    scopes = set(chunk_scopes or [])
    if "global" in scopes:
        return True
    return bool(scopes & _ELEMENT_SCOPES.get(element_kind, set()))


@dataclass
class OASElement:
    location: str      # e.g. "paths./items.post", "components.schemas.Item", "info"
    kind: str          # "info" | "operation" | "schema"
    description: str   # natural-language summary used as the retrieval query


def _schema_field_names(schema: dict) -> list[str]:
    props = schema.get("properties") if isinstance(schema, dict) else None
    return list(props.keys()) if isinstance(props, dict) else []


def _operation_description(path: str, method: str, op: dict) -> str:
    """A rich NL description of one operation, from its actual content —
    method, path, summary/description, parameter names, request body fields,
    response codes. This is what gets embedded to find relevant guidelines."""
    parts = [f"{method.upper()} {path}"]
    if op.get("summary"):
        parts.append(str(op["summary"]))
    if op.get("description"):
        parts.append(str(op["description"]))

    params = op.get("parameters") or []
    pnames = [f"{p.get('name')} ({p.get('in')})" for p in params if isinstance(p, dict) and p.get("name")]
    if pnames:
        parts.append("parameters: " + ", ".join(pnames))

    body = op.get("requestBody")
    if isinstance(body, dict):
        for _mt, media in (body.get("content") or {}).items():
            fields = _schema_field_names((media or {}).get("schema") or {})
            if fields:
                parts.append("request body fields: " + ", ".join(fields))
                break

    responses = op.get("responses") or {}
    if responses:
        parts.append("responses: " + ", ".join(str(c) for c in responses))
    return ". ".join(parts)


def extract_oas_elements(spec: dict) -> list[OASElement]:
    """Break a parsed OAS into the addressable pieces a guideline could
    apply to. Order: info, then operations, then component schemas."""
    elements: list[OASElement] = []

    info = spec.get("info") or {}
    if info:
        desc = "API metadata. " + ". ".join(
            str(info[k]) for k in ("title", "version", "description") if info.get(k)
        )
        elements.append(OASElement("info", "info", desc))

    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() in _HTTP_METHODS and isinstance(op, dict):
                elements.append(OASElement(
                    location=f"paths.{path}.{method.lower()}",
                    kind="operation",
                    description=_operation_description(path, method, op),
                ))

    schemas = ((spec.get("components") or {}).get("schemas")) or {}
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        fields = _schema_field_names(schema)
        desc = f"Schema {name}" + (". fields: " + ", ".join(fields) if fields else "")
        elements.append(OASElement(f"components.schemas.{name}", "schema", desc))

    return elements


def link_guidelines(spec: dict) -> list[GuidelineViolation]:
    """For each OAS element, retrieve the closest guideline chunks and
    return them as notes anchored (via `path`) to that element's location.
    Deduped so the same guideline chunk isn't repeated under one location,
    ranked by closeness, capped at MAX_NOTES."""
    anchored: list[tuple[float, GuidelineViolation]] = []
    seen: set[tuple[str, str | None, str]] = set()

    for element in extract_oas_elements(spec):
        kept = 0
        # Over-fetch so that skipping non-rules doesn't shrink the count.
        for doc, score in retrieve_with_scores(Index.GUIDELINES, element.description, k=K_PER_ELEMENT + 3):
            # Exclude chunks the LLM tagger marked as reference/onboarding
            # material (is_rule False) — those clutter auto-anchoring with
            # things like tool docs. They're still findable via
            # get_guideline_section (explicit lookup). Missing/None is_rule
            # (keyword tagger, legacy) is treated as a rule = included.
            if doc.metadata.get("is_rule") is False:
                continue
            # Phase 2: scope-aware soft boost — a scope-matching guideline
            # gets a lower (better) effective distance, so it out-ranks a
            # merely-text-similar one and is likelier to survive the cutoff.
            adjusted = score - SCOPE_BOOST if _scope_match(doc.metadata.get("scope"), element.kind) else score
            if SCORE_THRESHOLD is not None and adjusted > SCORE_THRESHOLD:
                continue
            key = (element.location, doc.metadata.get("section"), doc.page_content[:80])
            if key in seen:
                continue
            seen.add(key)
            anchored.append((adjusted, GuidelineViolation(
                rule_id="guideline-link",
                message=doc.page_content[:400],
                path=element.location,
                severity="info",
                source="rag",
                source_document=doc.metadata.get("source"),
                source_section=doc.metadata.get("section"),
            )))
            kept += 1
            if kept >= K_PER_ELEMENT:
                break

    anchored.sort(key=lambda pair: pair[0])  # closest (scope-adjusted) first
    return [v for _, v in anchored[:MAX_NOTES]]
