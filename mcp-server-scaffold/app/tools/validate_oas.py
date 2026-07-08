"""
validate_oas — Spectral lint (findings enriched from the ruleset lookup
dict) + Guidelines Index retrieval for prose rules the linter can't check.
Returns a report; modifies nothing.
"""
from app.models import OASInput, ValidateOASResult, GuidelineViolation
from app.integrations.spectral import run_spectral
from app.rag.retriever import retrieve_guidelines

TOOL_DESCRIPTION = (
    "Validate an OpenAPI spec against API Design Guidelines. Returns "
    "violations (with rule explanations and suggested fixes) plus relevant "
    "guideline excerpts. Does not modify the spec."
)


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


def validate_oas(payload: OASInput) -> ValidateOASResult:
    spectral = run_spectral(payload.oas_content, payload.format)
    notes = guideline_context(payload.oas_content)
    errors = [v for v in spectral if v.severity == "error"]
    return ValidateOASResult(
        is_valid=not errors,
        violations=spectral + notes,
        summary=f"{len(spectral)} Spectral finding(s) ({len(errors)} error(s)); "
                f"{len(notes)} guideline note(s) from the knowledge base.",
    )
