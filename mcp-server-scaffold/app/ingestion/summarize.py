"""
Guidelines summary — one consolidated, condensed digest of every design/
security rule in the corpus, built ONCE at ingestion (SCOPE_TAGGER=llm
only, since it needs is_rule to tell rule chunks from reference material)
and persisted alongside the FAISS index. validate_oas/fix_oas then just
read the saved text and attach it to every response (guidelines_summary)
— no LLM call on the live request path, same offline/one-shot pattern as
the scope tagger.

Why: per-element retrieval (app/rag/guideline_linker.py) is precise but
inherently partial — it only surfaces the top-K nearest chunks per
element, so a rule that's real but doesn't score close enough (or applies
in a way the retrieval query didn't capture) can be missed entirely. This
summary is the deliberate complement: everything, condensed, so the
calling agent has whole-corpus context to catch what anchoring missed —
not a replacement for the precise, per-location notes.

Cost: one chat call total per ingestion run (not per chunk) — cheap
regardless of corpus size. Caveat: a single call has a context limit: for
a much larger real guidelines corpus than the sample doc this is tuned
against, joined chunk text may need to be map-reduced (summarize in
groups, then combine) instead of one pass — not implemented, since the
current corpus is small; revisit if summaries start looking truncated or
thin.
"""
import logging

logger = logging.getLogger(__name__)

# Rough character budget for one chat call's input. Conservative for a
# ~8k-token context model at 4 chars/token; leaves room for the prompt itself.
_MAX_INPUT_CHARS = 24000

_PROMPT = """You are given excerpts from an API design guideline document —
every excerpt is a rule the design/security guidelines actually state (in
naming, versioning, pagination, error handling, security, idempotency, etc).

Produce ONE consolidated summary covering every distinct rule below.
Condense — don't quote verbatim — but do not drop or merge away any
distinct requirement; a validator will rely on this summary to catch
rules that a narrower per-element search might miss. Organize by topic
with short headings. Omit nothing substantive; omit nothing that isn't
substantive shouldn't be here in the first place (these are pre-filtered
to rule content already).

Guideline excerpts:
---
{excerpts}
---

Respond with ONLY the summary text (no preamble, no markdown fences)."""


def summarize_guidelines(chunks) -> str | None:
    """chunks: the same chunk objects passed through _tag_scopes (each has
    .text and .metadata with an is_rule key when SCOPE_TAGGER=llm ran).
    Returns None if there's nothing to summarize or the call fails — never
    breaks ingestion."""
    rule_chunks = [c for c in chunks if c.metadata.get("is_rule") is not False]
    if not rule_chunks:
        return None

    excerpts = []
    total = 0
    for c in rule_chunks:
        section = c.metadata.get("section") or ""
        piece = f"[{section}]\n{c.text}" if section else c.text
        if total + len(piece) > _MAX_INPUT_CHARS:
            break
        excerpts.append(piece)
        total += len(piece)

    try:
        from app.integrations.internal_llm import get_chat_model

        summary = get_chat_model().invoke(_PROMPT.format(excerpts="\n\n".join(excerpts))).content
        return (summary or "").strip() or None
    except Exception:
        logger.warning("Guidelines summary generation failed; validate_oas/fix_oas will omit "
                        "guidelines_summary", exc_info=True)
        return None
