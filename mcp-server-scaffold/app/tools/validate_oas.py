"""
validate_oas — Spectral lint (findings enriched from the ruleset lookup
dict) + Guidelines Index retrieval for prose rules the linter can't check.
Returns a report; modifies nothing.
"""
import logging

from app.models import OASInput, ValidateOASResult, GuidelineViolation
from app.integrations.spectral import run_spectral
from app.rag.retriever import retrieve_guidelines, get_section_chunks, build_guidelines_toc

logger = logging.getLogger(__name__)


def guideline_context(oas_content: str, k: int = 4) -> list[GuidelineViolation]:
    """Surface guideline chunks relevant to this OAS as informational notes,
    each citing the doc/section it came from."""
    docs = retrieve_guidelines(f"API design rules relevant to: {oas_content[:600]}", k=k)
    return [
        GuidelineViolation(
            rule_id="guideline-context",
            message=d.page_content[:400],
            severity="info",
            source="rag",
            source_document=d.metadata.get("source"),
            source_section=d.metadata.get("section"),
        )
        for d in docs
    ]


def attach_guideline_excerpts(findings: list[GuidelineViolation]) -> None:
    """Give each custom-ruleset finding the actual prose of the guideline
    section it enforces (via the rule's x-guideline-section citation) —
    exact section-name fetch, no similarity search."""
    for v in findings:
        if v.source == "custom-ruleset" and v.source_section and not v.guideline_excerpt:
            chunks = get_section_chunks(v.source_section, document=v.source_document)
            if chunks:
                v.guideline_excerpt = "\n".join(c.page_content for c in chunks)[:600]


def validate_oas(payload: OASInput) -> ValidateOASResult:
    spectral = run_spectral(payload.oas_content, payload.format)
    attach_guideline_excerpts(spectral)
    notes = guideline_context(payload.oas_content)

    spectral_core = [v for v in spectral if v.source == "spectral-core"]
    org_ruleset = [v for v in spectral if v.source == "custom-ruleset"]
    errors = [v for v in spectral if v.severity == "error"]

    if errors:
        next_step = ("This validation report is the answer if the user only asked to validate — "
                     "present it grouped into three sections: Spectral lint findings "
                     "(source=spectral-core, generic OpenAPI best practices), Custom Ruleset "
                     "findings (source=custom-ruleset, Org-specific mechanically-enforced rules, "
                     "each carrying the guideline prose it enforces in guideline_excerpt), "
                     "and Guideline notes (source=rag, prose guidance) — don't merge them into "
                     "one flat list. Only call fix_oas if the user separately asks you to fix or "
                     "correct the spec; if they do, call it with this same oas_content, apply "
                     "the fixes yourself, then call validate_oas again.")
    elif spectral:
        next_step = ("No blocking errors, but there are warnings above — report them (grouped by "
                     "source: spectral-core vs custom-ruleset) and the guideline notes (source=rag) "
                     "to the user. Only pursue a fix if the user asks for one.")
    else:
        next_step = ("Spec is fully compliant. Review the guideline notes (source=rag) for any "
                     "manual judgment calls; no fix needed. guidelines_toc lists every guideline "
                     "section — call get_guideline_section if the user asks about one in depth.")

    logger.info(
        "validate_oas: api_name=%s oas_len=%d -> is_valid=%s spectral_core=%d org_ruleset=%d "
        "guideline_notes=%d errors=%d",
        payload.api_name, len(payload.oas_content), not errors,
        len(spectral_core), len(org_ruleset), len(notes), len(errors),
    )

    return ValidateOASResult(
        is_valid=not errors,
        violations=spectral + notes,
        summary=f"{len(spectral_core)} Spectral lint finding(s), {len(org_ruleset)} Org ruleset "
                f"finding(s) ({len(errors)} error(s) total); {len(notes)} guideline note(s) "
                f"from the knowledge base.",
        next_step=next_step,
        guidelines_toc=build_guidelines_toc(),
    )
