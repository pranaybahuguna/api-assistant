"""
validate_oas — Spectral lint + Guidelines Index retrieval. Returns a
report; modifies nothing.

How the pieces fit (shared with fix_oas via analyze_oas):

1. Parse ladder: try to parse oas_content (declared format first, then the
   other). Spectral ALWAYS runs regardless — on unparseable input it
   reports `parser` errors with line numbers, which become the blocking
   findings. A parsed-but-not-OAS document (no openapi/swagger key, no
   paths) gets a synthetic structural finding instead of twenty confusing
   lint results.
2. Guideline retrieval: for a parsed spec, queries are FACTS derived from
   walking the actual document ("POST endpoints that create resources",
   "uses skip/take pagination", ...) — each fact is retrieved separately
   and results are merged/deduped, so every note is present for a reason.
   For a malformed spec it falls back to one raw-text query: degraded but
   still useful, and clearly labeled anticipatory context in next_step.
3. custom-ruleset findings additionally get the actual guideline prose of the
   section they enforce (guideline_excerpt), fetched by exact section
   match — no similarity search involved.
"""
import json
import logging
import re

import yaml

from app.models import OASInput, ValidateOASResult, GuidelineViolation
from app.integrations.spectral import run_spectral, SpectralError
from app.rag.retriever import retrieve_guidelines, get_section_chunks, build_guidelines_toc, get_guidelines_summary
from app.rag.guideline_linker import link_guidelines

logger = logging.getLogger(__name__)

_VERSIONED_PATH_RE = re.compile(r"^/v\d+/")
_MAX_GUIDELINE_NOTES = 6
_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


# ---------------------------------------------------------- parse ladder ----

def parse_oas(oas_content: str, fmt: str) -> tuple[dict | None, str | None, str | None]:
    """Returns (parsed, syntax_error, structure_error). parsed is None
    whenever either error is set — a syntactically broken document can't
    be walked, and a parseable-but-not-OAS document shouldn't be (its
    'facts' would be nonsense)."""
    parsers = [yaml.safe_load, json.loads] if fmt == "yaml" else [json.loads, yaml.safe_load]
    parsed, first_error = None, None
    for parser in parsers:
        try:
            parsed = parser(oas_content)
            break
        except Exception as e:
            first_error = first_error or str(e)
    if parsed is None:
        return None, f"Document does not parse as YAML or JSON: {first_error[:300]}", None
    if not isinstance(parsed, dict) or not ("openapi" in parsed or "swagger" in parsed):
        return None, None, ("Content parses, but is not an OpenAPI document — no "
                            "'openapi' or 'swagger' version key found.")
    return parsed, None, None


# ----------------------------------------------------- fact derivation ----

def derive_facts(spec: dict) -> list[str]:
    """Natural-language retrieval queries derived from what the spec
    actually contains — each becomes one small guideline lookup, so
    retrieved notes are tied to real characteristics of THIS spec."""
    paths = spec.get("paths") or {}
    operations = [
        (path, method, op)
        for path, methods in paths.items() if isinstance(methods, dict)
        for method, op in methods.items() if method in _HTTP_METHODS and isinstance(op, dict)
    ]

    param_names: set[str] = set()
    status_codes: set[str] = set()
    any_security = False
    for _, _, op in operations:
        for p in op.get("parameters") or []:
            if isinstance(p, dict) and p.get("name"):
                param_names.add(str(p["name"]).lower())
        for code in (op.get("responses") or {}):
            status_codes.add(str(code))
        if op.get("security"):
            any_security = True

    facts = ["resource naming conventions for REST API paths"]  # prose-only rule, always relevant
    if any(m == "post" for _, m, _ in operations):
        facts.append("POST endpoints creating resources and idempotency requirements")
    if paths and not all(_VERSIONED_PATH_RE.match(str(p)) for p in paths):
        facts.append("URL path versioning requirements")
    if {"skip", "take", "limit", "offset"} & param_names:
        facts.append("pagination parameters and their limits")
    if any(c.startswith(("4", "5")) for c in status_codes):
        facts.append("error response format and error envelope")
    if "429" in status_codes:
        facts.append("rate limiting and Retry-After headers")
    if not any_security:
        facts.append("authentication and OAuth2 security requirements")
    return facts


# ------------------------------------------------- guideline retrieval ----

def _note(doc) -> GuidelineViolation:
    return GuidelineViolation(
        rule_id="guideline-context",
        message=doc.page_content[:400],
        severity="info",
        source="rag",
        source_document=doc.metadata.get("source"),
        source_section=doc.metadata.get("section"),
    )


def guideline_context(oas_content: str, parsed: dict | None) -> list[GuidelineViolation]:
    """Structural anchoring for a parsed spec (guideline notes carry a
    `path` pointing at the OAS element they apply to — see
    app/rag/guideline_linker.py); one raw-text query as the degraded
    fallback for malformed input."""
    if parsed is not None:
        notes = link_guidelines(parsed)
        logger.info("guideline_context: anchored %d guideline note(s) to OAS elements", len(notes))
        return notes

    logger.info("guideline_context: spec not parseable — raw-text fallback query")
    docs = retrieve_guidelines(f"API design rules relevant to: {oas_content[:600]}", k=4)
    notes, seen = [], set()
    for d in docs:
        key = (d.metadata.get("source"), d.metadata.get("section"), d.page_content[:80])
        if key in seen:
            continue
        seen.add(key)
        notes.append(_note(d))
    return notes[:_MAX_GUIDELINE_NOTES]


def attach_guideline_excerpts(findings: list[GuidelineViolation]) -> None:
    """Give each custom-ruleset finding the actual prose of the guideline
    section it enforces — exact section-name fetch, no similarity search."""
    for v in findings:
        if v.source == "custom-ruleset" and v.source_section and not v.guideline_excerpt:
            chunks = get_section_chunks(v.source_section, document=v.source_document)
            if chunks:
                v.guideline_excerpt = "\n".join(c.page_content for c in chunks)[:600]


# ------------------------------------------------------- shared analysis ----

def analyze_oas(payload: OASInput):
    """Everything validate_oas and fix_oas have in common: parse ladder,
    Spectral run, guideline retrieval, excerpt attachment, TOC, and the
    consolidated guidelines summary (see app/ingestion/summarize.py) — the
    latter is just a disk read (or None), not a live LLM call.

    Spectral sometimes crashes outright (exit 2, internal error) on
    malformed input instead of emitting graceful `parser` findings — when
    the document already failed OUR parse ladder, that crash is tolerated
    and the synthetic parse-error finding carries the diagnosis instead.
    On a document that parses fine, a Spectral failure is a real
    server-side problem and still raises."""
    parsed, syntax_error, structure_error = parse_oas(payload.oas_content, payload.format)

    try:
        findings = run_spectral(payload.oas_content, payload.format)
    except SpectralError:
        if parsed is not None and not structure_error:
            raise
        logger.warning("Spectral failed on unparseable/non-OAS input; using synthetic findings only")
        findings = []

    if syntax_error:
        findings.insert(0, GuidelineViolation(
            rule_id="parse-error", message=syntax_error,
            severity="error", source="spectral-core",
        ))
    if structure_error:
        findings.insert(0, GuidelineViolation(
            rule_id="oas-structure", message=structure_error,
            severity="error", source="spectral-core",
        ))
    attach_guideline_excerpts(findings)

    notes = guideline_context(payload.oas_content, parsed)
    return parsed, findings, notes, build_guidelines_toc(), get_guidelines_summary()


# ------------------------------------------------------------ the tool ----

def validate_oas(payload: OASInput) -> ValidateOASResult:
    parsed, spectral, notes, toc, guidelines_summary = analyze_oas(payload)

    spectral_core = [v for v in spectral if v.source == "spectral-core"]
    org_ruleset = [v for v in spectral if v.source == "custom-ruleset"]
    errors = [v for v in spectral if v.severity == "error"]
    parse_errors = [v for v in spectral if v.rule_id in ("parser", "parse-error", "oas-structure")]

    if parsed is None or parse_errors:
        next_step = ("The spec is malformed or not a valid OpenAPI document — the parser/structure "
                     "findings above are the blocking problem, and deeper rule findings stay hidden "
                     "until it parses. The guideline notes (source=rag) are anticipatory context "
                     "retrieved from the raw text, not confirmed findings. If the user only asked to "
                     "validate, report this as-is. If the user asked for a fix: correct the syntax AND "
                     "apply the guideline context in the same edit, then call validate_oas again — "
                     "expect new findings to surface once the document parses.")
    elif errors:
        next_step = ("This validation report is the answer if the user only asked to validate — "
                     "present these findings grouped into three sections: Spectral lint findings "
                     "(source=spectral-core, generic OpenAPI best practices), Custom Ruleset findings "
                     "(source=custom-ruleset, Org-specific mechanically-enforced rules, each carrying "
                     "the guideline prose it enforces in guideline_excerpt), and Guideline notes "
                     "(source=rag) — don't merge them into one flat list. Only call fix_oas if the "
                     "user separately asks you to fix or correct the spec.")
    elif spectral:
        next_step = ("No blocking errors, but there are warnings above — report them (grouped by "
                     "source: spectral-core vs custom-ruleset) and the guideline notes (source=rag) "
                     "to the user. Only pursue a fix if the user asks for one.")
    else:
        next_step = ("Spec is fully compliant. Review the guideline notes (source=rag) for any "
                     "manual judgment calls; no fix needed. guidelines_toc lists every guideline "
                     "section — call get_guideline_section if the user asks about one in depth.")

    if guidelines_summary:
        next_step += (" guidelines_summary is a condensed whole-corpus digest of every design/"
                      "security rule — cross-check the spec against it too, since the "
                      "violations/notes above only cover what per-element retrieval surfaced "
                      "and can miss a rule that's real but scored too far to be included.")

    logger.info(
        "validate_oas: api_name=%s oas_len=%d parsed=%s -> is_valid=%s spectral_core=%d "
        "org_ruleset=%d guideline_notes=%d errors=%d",
        payload.api_name, len(payload.oas_content), parsed is not None, not errors,
        len(spectral_core), len(org_ruleset), len(notes), len(errors),
    )

    return ValidateOASResult(
        is_valid=not errors,
        violations=spectral + notes,
        summary=f"{len(spectral_core)} Spectral lint finding(s), {len(org_ruleset)} Org ruleset "
                f"finding(s) ({len(errors)} error(s) total); {len(notes)} guideline note(s) "
                f"from the knowledge base."
                + (" Spec did not parse — deeper findings hidden until syntax is fixed." if parsed is None else ""),
        next_step=next_step,
        guidelines_toc=toc,
        guidelines_summary=guidelines_summary,
    )
