"""
fix_oas — produces a fix plan (Spectral findings + Guidelines context) for
the calling agent to act on. Does NOT call an LLM to rewrite the spec
itself: the calling agent has its own LLM and applies the fixes — this
tool only tells it what's wrong, and how to fix it where the ruleset
defines a concrete suggested_fix. The only LLM-style calls this server
makes are embeddings and OCR; spec rewriting is the client's job.
"""
import logging

from app.models import OASInput, FixOASResult
from app.integrations.spectral import run_spectral
from app.tools.validate_oas import guideline_context

logger = logging.getLogger(__name__)


def fix_oas(payload: OASInput) -> FixOASResult:
    findings = run_spectral(payload.oas_content, payload.format)
    notes = guideline_context(payload.oas_content)

    mechanical = [v for v in findings if v.suggested_fix]
    needs_judgment = [v for v in findings if not v.suggested_fix]

    logger.info(
        "fix_oas: api_name=%s oas_len=%d -> mechanical_fixes=%d needs_judgment=%d guideline_notes=%d",
        payload.api_name, len(payload.oas_content), len(mechanical), len(needs_judgment), len(notes),
    )

    if not findings:
        next_step = "No violations found — spec already complies. No changes needed."
    else:
        parts = []
        if mechanical:
            parts.append("apply each mechanical_fixes entry's suggested_fix as stated")
        if needs_judgment:
            parts.append("for each needs_judgment entry, use its rule_explanation "
                          "(and guideline_notes for context) to decide the right change")
        next_step = ("You (the calling agent) must edit oas_content yourself — this tool does "
                     "not rewrite it: " + "; ".join(parts) + ". Then call validate_oas on your "
                     "edited spec to confirm the fixes actually resolved the findings.")

    return FixOASResult(
        mechanical_fixes=mechanical,
        needs_judgment=needs_judgment,
        guideline_notes=notes,
        summary=f"{len(findings)} Spectral finding(s): {len(mechanical)} with a concrete "
                f"suggested fix, {len(needs_judgment)} needing judgment; "
                f"{len(notes)} guideline note(s) for context.",
        next_step=next_step,
    )
