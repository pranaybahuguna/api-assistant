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
_NO_COMMENTS = ("Edit oas_content directly — do not add comments (# in YAML, // or /* */ in "
                "JSON) to explain your edit. In JSON format a comment breaks parsing outright "
                "(invalid JSON — the next validate_oas call sees a malformed spec), and even in "
                "YAML it's noise the guidelines never asked for.")
_SHOW_RESULT = ("This plan is input for you to act on, not the final answer — do not paste it, "
                "list it, or otherwise present these findings to the user as steps to follow; "
                "the user asked for the fix, not instructions. Your reply must contain the "
                "actual corrected oas_content in full, plus a short summary of what changed. If "
                "you have not produced the edited spec text, you are not done.")


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
                     "guideline_notes context, so your edit addresses both. " + _NO_COMMENTS +
                     " Then call validate_oas on your edited spec — expect new rule findings to "
                     "surface once the document parses; fix those and validate again. " +
                     _LOOP_BOUND + " " + _SHOW_RESULT)
    elif not findings:
        next_step = "No violations found — spec already complies. No changes needed."
    else:
        parts = []
        if mechanical:
            parts.append("apply each mechanical_fixes entry's suggested_fix as stated (its "
                          "guideline_excerpt carries the guideline text behind the rule)")
        if needs_judgment:
            parts.append("for each needs_judgment entry, use its rule_explanation "
                          "(and guideline_notes for context) to decide the right change")
        next_step = ("You (the calling agent) must edit oas_content yourself — this tool does "
                     "not rewrite it: " + "; ".join(parts) + ". " + _NO_COMMENTS + " Then call "
                     "validate_oas on your edited spec to confirm the fixes actually resolved "
                     "the findings. " + _LOOP_BOUND + " " + _SHOW_RESULT)

    if guidelines_summary:
        next_step += (" guideline_notes above is the Design Guidelines set (source=rag, "
                      "recommendations sourced from the design guidelines). It's worth checking "
                      "guidelines_summary — a condensed whole-corpus digest of every design/"
                      "security rule — against oas_content too, since this run's retrieval only "
                      "surfaces the top-K nearest guideline chunks per element. This is advisory, "
                      "not a new blocking violation: only act on it if you find something "
                      "concrete that mechanical_fixes/needs_judgment/guideline_notes don't "
                      "already cover — don't manufacture a fix just to seem thorough, and don't "
                      "re-raise something you already flagged earlier in this conversation for "
                      "the same spec. Once mechanical_fixes/needs_judgment are resolved and "
                      "validate_oas reports is_valid=true, the spec is compliant — a "
                      "guidelines_summary observation on a later round is a suggestion for the "
                      "user, not a reason to keep editing and re-validating.")

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
