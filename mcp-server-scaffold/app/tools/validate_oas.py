"""
validate_oas — Spectral lint (findings enriched from the ruleset lookup
dict) + Guidelines Index retrieval for prose rules the linter can't check.
Returns a report; modifies nothing.
"""
from app.models import OASInput, ValidateOASResult, GuidelineViolation
from app.integrations.spectral import run_spectral
from app.rag.retriever import retrieve_guidelines


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
    errors = [v for v in spectral if v.severity == "error"]

    if errors:
        next_step = ("This validation report is the answer if the user only asked to validate — "
                     "present these findings as-is. Only call fix_oas if the user separately "
                     "asks you to fix or correct the spec; if they do, call it with this same "
                     "oas_content, apply the fixes yourself, then call validate_oas again.")
    elif spectral:
        next_step = ("No blocking errors, but there are warnings above — report them and the "
                     "guideline notes (source=rag) to the user. Only pursue a fix if the user "
                     "asks for one.")
    else:
        next_step = "Spec is fully compliant. Review the guideline notes (source=rag) for any manual judgment calls; no fix needed."

    return ValidateOASResult(
        is_valid=not errors,
        violations=spectral + notes,
        summary=f"{len(spectral)} Spectral finding(s) ({len(errors)} error(s)); "
                f"{len(notes)} guideline note(s) from the knowledge base.",
        next_step=next_step,
    )
