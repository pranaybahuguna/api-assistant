"""
fix_oas — produces a fix plan (Spectral findings + Guidelines context) for
the calling agent to act on. Does NOT call an LLM to rewrite the spec
itself: the calling agent has its own LLM and applies the fixes — this
tool only tells it what's wrong, and how to fix it where the ruleset
defines a concrete suggested_fix. The only LLM-style calls this server
makes are embeddings and OCR; spec rewriting is the client's job.
"""
from app.models import OASInput, FixOASResult
from app.integrations.spectral import run_spectral
from app.tools.validate_oas import guideline_context

TOOL_DESCRIPTION = (
    "Produce a fix plan for an OpenAPI spec against Org API Design "
    "Guidelines: Spectral findings split into ones with a concrete "
    "suggested fix vs. ones needing judgment, plus relevant guideline "
    "excerpts. Does not rewrite the spec — the caller applies the fixes."
)


def fix_oas(payload: OASInput) -> FixOASResult:
    findings = run_spectral(payload.oas_content, payload.format)
    notes = guideline_context(payload.oas_content)

    mechanical = [v for v in findings if v.suggested_fix]
    needs_judgment = [v for v in findings if not v.suggested_fix]

    return FixOASResult(
        mechanical_fixes=mechanical,
        needs_judgment=needs_judgment,
        guideline_notes=notes,
        summary=f"{len(findings)} Spectral finding(s): {len(mechanical)} with a concrete "
                f"suggested fix, {len(needs_judgment)} needing judgment; "
                f"{len(notes)} guideline note(s) for context.",
    )
