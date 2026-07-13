"""
Guideline linker (Phase 1: structural anchoring).

The old approach ran a few whole-spec queries and returned a flat list of
guideline notes with no sense of WHERE in the OAS each one applied. This
inverts it: decompose the spec into addressable elements (the info block,
each operation, each schema), retrieve guidelines per element, and anchor
each hit to the element's location so a note reads "this guideline applies
to paths./items.post" instead of floating unattached.

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
SCORE_THRESHOLD: float | None = None


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
        for doc, score in retrieve_with_scores(Index.GUIDELINES, element.description, k=K_PER_ELEMENT):
            if SCORE_THRESHOLD is not None and score > SCORE_THRESHOLD:
                continue
            key = (element.location, doc.metadata.get("section"), doc.page_content[:80])
            if key in seen:
                continue
            seen.add(key)
            anchored.append((score, GuidelineViolation(
                rule_id="guideline-link",
                message=doc.page_content[:400],
                path=element.location,
                severity="info",
                source="rag",
                source_document=doc.metadata.get("source"),
                source_section=doc.metadata.get("section"),
            )))

    anchored.sort(key=lambda pair: pair[0])  # closest first
    return [v for _, v in anchored[:MAX_NOTES]]
