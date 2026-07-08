"""
validate_oas — three layers of checks, in order of how deterministic they
are:

1. Spectral lint (structural rules — pagination limits, versioned paths,
   error envelope, idempotency header, etc.), findings enriched from the
   ruleset lookup dict.
2. Guidelines Index (RAG) — prose rules Spectral can't check structurally
   (naming conventions, deprecation windows), surfaced as informational
   context, not violations, since retrieval isn't a pass/fail check.
3. Referential + Registry cross-checks (RAG) — functional requirements that
   live outside the spec itself: is this API even registered in the
   inventory, and does any operation in it duplicate functionality another
   team already shipped? These are the "does this fit Org's API landscape"
   checks the Guidelines doc alone can't answer, because that answer
   depends on what other APIs already exist, not on rules.

Only Spectral errors affect is_valid — the Referential/Registry checks are
similarity-based (nearest neighbour in embedding space), so they are
reported as warnings for a human/agent to judge, never a hard fail.

Returns a report; modifies nothing.
"""
import json

import yaml

from app.models import OASInput, ValidateOASResult, GuidelineViolation
from app.integrations.spectral import run_spectral
from app.rag.retriever import retrieve_guidelines, retrieve_referential, retrieve_registry

TOOL_DESCRIPTION = (
    "Validate an OpenAPI spec against API Design Guidelines. Returns "
    "violations (with rule explanations and suggested fixes) plus relevant "
    "guideline excerpts. Does not modify the spec."
)

# Below this L2 distance, a nearest-neighbour hit is treated as "the same
# API/endpoint" rather than just topically related — picked from observed
# score ranges (true matches score ~0.6-0.9, unrelated hits score >1.3).
_SIMILARITY_THRESHOLD = 0.9


def _load_oas(oas_content: str, fmt: str) -> dict:
    try:
        return (yaml.safe_load(oas_content) if fmt == "yaml" else json.loads(oas_content)) or {}
    except Exception:
        return {}


def guideline_context(oas_content: str, k: int = 4) -> list[GuidelineViolation]:
    """Surface guideline chunks relevant to this OAS as informational notes."""
    docs = retrieve_guidelines(f"API design rules relevant to: {oas_content[:600]}", k=k)
    return [
        GuidelineViolation(
            rule_id="guideline-context",
            message=d.page_content[:400],
            severity="info",
            source="rag",
        )
        for d in docs
    ]


def referential_context(api_name: str | None, oas_content: str, fmt: str) -> list[GuidelineViolation]:
    """Is this API registered in the Referential, and does it look like a
    near-duplicate of an already-registered API under a different name?"""
    doc = _load_oas(oas_content, fmt)
    info = doc.get("info", {}) if isinstance(doc, dict) else {}
    name = api_name or info.get("title", "")
    if not name:
        return []

    description = info.get("description", "")
    query = f"{name}: {description}" if description else name
    hits = retrieve_referential(query, k=1)

    if not hits:
        return [GuidelineViolation(
            rule_id="referential-not-registered",
            message=f"'{name}' was not found in the API Referential inventory — "
                     "register it there before onboarding.",
            severity="warning", source="referential",
        )]

    match, score = hits[0]
    existing_name = match.metadata.get("api_name", "")
    if score <= _SIMILARITY_THRESHOLD and existing_name.lower() != name.lower():
        return [GuidelineViolation(
            rule_id="referential-possible-duplicate",
            message=f"'{name}' looks very similar to the already-registered '{existing_name}' "
                     f"({match.metadata.get('api_id', '?')}) — confirm this isn't duplicate functionality "
                     "before onboarding a new API.",
            severity="warning", source="referential",
        )]
    return [GuidelineViolation(
        rule_id="referential-context",
        message=f"Closest Referential match: '{existing_name}' ({match.metadata.get('api_id', '?')}).",
        severity="info", source="referential",
    )]


def registry_context(oas_content: str, fmt: str, api_name: str | None) -> list[GuidelineViolation]:
    """Does any operation in this spec duplicate functionality another API
    in the Registry already offers? Cross-team endpoint overlap is a
    functional-fit problem the guidelines/Spectral can't catch — it depends
    on what other teams have already built, not on this spec in isolation."""
    doc = _load_oas(oas_content, fmt)
    paths = doc.get("paths", {}) if isinstance(doc, dict) else {}
    violations: list[GuidelineViolation] = []

    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, op in operations.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            summary = op.get("summary", "")
            query = f"{method.upper()} {path}: {summary}" if summary else f"{method.upper()} {path}"
            hits = retrieve_registry(query, k=1)
            if not hits:
                continue
            match, score = hits[0]
            existing_api = match.metadata.get("api_name", "")
            if score <= _SIMILARITY_THRESHOLD and existing_api.lower() != (api_name or "").lower():
                existing_endpoint = (f"{match.metadata['method']} {match.metadata['path']}"
                                      if match.metadata.get("method") else "an existing endpoint")
                violations.append(GuidelineViolation(
                    rule_id="registry-possible-duplicate",
                    message=f"{method.upper()} {path} looks very similar to {existing_endpoint} already "
                             f"offered by '{existing_api}' ({match.metadata.get('api_id', '?')}) — "
                             "consider reusing it instead of duplicating functionality.",
                    path=path,
                    severity="warning", source="registry",
                ))
    return violations


def validate_oas(payload: OASInput) -> ValidateOASResult:
    spectral = run_spectral(payload.oas_content, payload.format)
    guideline_notes = guideline_context(payload.oas_content)
    referential_notes = referential_context(payload.api_name, payload.oas_content, payload.format)
    registry_notes = registry_context(payload.oas_content, payload.format, payload.api_name)

    errors = [v for v in spectral if v.severity == "error"]
    return ValidateOASResult(
        is_valid=not errors,
        violations=spectral + guideline_notes + referential_notes + registry_notes,
        summary=f"{len(spectral)} Spectral finding(s) ({len(errors)} error(s)); "
                f"{len(guideline_notes)} guideline note(s); "
                f"{len(referential_notes)} referential note(s); "
                f"{len(registry_notes)} registry note(s).",
    )
