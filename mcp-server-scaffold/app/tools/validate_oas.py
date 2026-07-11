"""
validate_oas — Spectral lint (findings enriched from the ruleset lookup
dict) + Guidelines Index retrieval for prose rules the linter can't check.
Returns a report; modifies nothing.
"""
import logging

from app.models import OASInput, ValidateOASResult, GuidelineViolation
from app.integrations.spectral import run_spectral
from app.rag.retriever import retrieve_guidelines

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


def validate_oas(payload: OASInput) -> ValidateOASResult:
    spectral = run_spectral(payload.oas_content, payload.format)
    notes = guideline_context(payload.oas_content)

    spectral_core = [v for v in spectral if v.source == "spectral-core"]
    org_ruleset = [v for v in spectral if v.source == "custom-ruleset"]
    errors = [v for v in spectral if v.severity == "error"]

    _FORMAT = ("Present the report to the user as exactly these four sections, in this order "
               "— don't merge them into one flat list:\n"
               "1. Spectral Lint Errors & Warnings — violations with source=spectral-core "
               "(generic OpenAPI best practices).\n"
               "2. Custom Ruleset Recommendations & Warnings — violations with source=custom-ruleset "
               "(Org-specific mechanically-enforced rules), each with its rule_explanation and "
               "suggested_fix.\n"
               "3. Org API Guideline Recommendations — notes with source=rag (prose guidance "
               "retrieved from the Guidelines Index), cited by source_document/source_section.\n"
               "4. Summary & Next Steps — a short summary of overall compliance status and what "
               "the user should do next.")

    if errors:
        next_step = (_FORMAT + " Only call fix_oas if the user separately asks you to fix or "
                     "correct the spec; if they do, call it with this same oas_content, apply "
                     "the fixes yourself, then call validate_oas again.")
    elif spectral:
        next_step = (_FORMAT + " No blocking errors, but section 1/2 above have warnings — "
                     "include them. Only pursue a fix if the user asks for one.")
    else:
        next_step = (_FORMAT + " Sections 1 and 2 will be empty — spec is fully compliant. "
                     "Still review section 3 for manual judgment calls; no fix needed.")

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
    )
