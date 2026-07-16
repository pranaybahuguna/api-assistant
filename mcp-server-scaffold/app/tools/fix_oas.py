"""
fix_oas — produces a fix plan (Spectral findings + Guidelines context) for
the calling agent to act on.

The canonical flow is validate_oas FIRST (diagnose, show the user), then
this tool (plan), then the agent edits, then validate_oas again (confirm).
Independently of that, validation also re-runs inside this tool on every
call: analyze_oas() (shared with validate_oas — same parse ladder, same
Spectral run, same guideline retrieval) reshapes fresh findings into the
plan. That's a stateless safety net — the server can't verify the agent
validated this exact content beforehand — not a replacement for the
explicit validate step.

Does NOT call an LLM to rewrite the spec itself: the calling agent has its
own LLM and applies the fixes — this tool only tells it what's wrong, and
how to fix it where the ruleset defines a concrete suggested_fix. The only
LLM-style calls this server makes are embeddings and OCR; spec rewriting
is the client's job, confirmed by calling validate_oas on the edited spec.
"""
import logging

from app.models import OASInput, FixOASResult
from app.tools.validate_oas import analyze_oas

logger = logging.getLogger(__name__)

_LOOP_BOUND = ("If findings persist after a couple of edit-and-validate rounds, stop and "
               "report the remaining findings to the user instead of iterating further.")


def fix_oas(payload: OASInput) -> FixOASResult:
    parsed, findings, notes, toc, guidelines_summary = analyze_oas(payload)

    mechanical = [v for v in findings if v.suggested_fix]
    needs_judgment = [v for v in findings if not v.suggested_fix]

    logger.info(
        "fix_oas: api_name=%s oas_len=%d parsed=%s -> mechanical_fixes=%d needs_judgment=%d guideline_notes=%d",
        payload.api_name, len(payload.oas_content), parsed is not None,
        len(mechanical), len(needs_judgment), len(notes),
    )

    if parsed is None:
        next_step = ("The spec is malformed — it doesn't parse. In ONE edit: fix the syntax "
                     "(see the parser/structure findings for line numbers) AND apply the "
                     "guideline_notes context, so your edit addresses both. Then call "
                     "validate_oas on your edited spec — expect new rule findings to surface "
                     "once the document parses; fix those and validate again. " + _LOOP_BOUND)
    elif not findings:
        next_step = "No violations found — spec already complies. No changes needed."
    else:
        parts = []
        if mechanical:
            parts.append("apply each mechanical_fixes entry's suggested_fix as stated (its "
                          "guideline_excerpt carries the guideline prose behind the rule)")
        if needs_judgment:
            parts.append("for each needs_judgment entry, use its rule_explanation "
                          "(and guideline_notes for context) to decide the right change")
        next_step = ("You (the calling agent) must edit oas_content yourself — this tool does "
                     "not rewrite it: " + "; ".join(parts) + ". Then call validate_oas on your "
                     "edited spec to confirm the fixes actually resolved the findings. " + _LOOP_BOUND)

    if guidelines_summary:
        next_step += (" guidelines_summary is a condensed whole-corpus digest of every design/"
                      "security rule — worth a pass against it too, since mechanical_fixes/"
                      "needs_judgment/guideline_notes only cover what this run's retrieval "
                      "surfaced and can miss a rule that's real but scored too far to include.")

    return FixOASResult(
        mechanical_fixes=mechanical,
        needs_judgment=needs_judgment,
        guideline_notes=notes,
        summary=f"{len(findings)} Spectral finding(s): {len(mechanical)} with a concrete "
                f"suggested fix, {len(needs_judgment)} needing judgment; "
                f"{len(notes)} guideline note(s) for context."
                + (" Spec did not parse — fix syntax first; more findings will surface once it parses." if parsed is None else ""),
        next_step=next_step,
        guidelines_toc=toc,
        guidelines_summary=guidelines_summary,
    )
