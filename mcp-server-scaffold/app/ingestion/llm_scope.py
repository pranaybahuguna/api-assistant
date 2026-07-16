"""
LLM guideline-scope tagger (optional alternative to the keyword tagger).

Enabled with SCOPE_TAGGER=llm at ingestion. For each guideline chunk it
makes ONE chat-model call and extracts a small rule-card — most importantly
the `scope` (which OAS constructs the rule governs), constrained to the
same vocabulary the keyword tagger uses, so it's a drop-in replacement. It
also captures `applies_when` and `check_type` for richer downstream use /
human inspection.

This is an ingestion-time (offline, one-shot, cacheable) call — not on the
live request path. Every failure falls back to the deterministic keyword
tagger, so a flaky/unavailable LLM never breaks ingestion.

Cost: one chat call per guideline chunk, once, when you (re)ingest with
SCOPE_TAGGER=llm. Review the produced cards before trusting them —
`applies_when` in particular is the highest-value but hardest field.
"""
import json
import logging
import re

from app.ingestion.scope_rules import SCOPES, infer_scopes

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_PROMPT = """You analyse a chunk from an API design guideline document.

First decide if it is an enforceable API DESIGN RULE (a "must/should" about how
an OpenAPI spec is built) versus REFERENCE / onboarding / example material
(tool download links, environment info, public-key examples, generic prose that
states no design requirement). Reference material is NOT a design rule.

If it IS a design rule, also say which OAS constructs it governs.
Allowed scope values (use only these): global, path, operation, query-param,
header, request-body, response, schema, security.
  - global: API-wide / applies broadly (naming philosophy, change management)
  - path: URL/endpoint structure (versioning, path casing)
  - operation: per-operation behaviour (idempotency, method semantics)
  - query-param, header, request-body, response, schema, security: the obvious ones

Guideline section: {section}
Guideline text:
---
{text}
---

Respond with ONLY this JSON (no markdown fences):
{{"is_design_rule": true or false,
  "scope": ["<one or more allowed values; use [\\"global\\"] if unsure or not a rule>"],
  "applies_when": "<short condition describing when this rule applies to an OAS element, or empty>",
  "check_type": "mechanical" or "judgment"}}"""


def _parse(raw: str) -> dict | None:
    for candidate in (raw, _FENCE_RE.sub("", raw).strip()):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and "scope" in parsed:
            return parsed
    return None


def llm_infer_scopes(section: str | None, text: str) -> tuple[list[str], dict]:
    """Returns (scope, extra). scope is a validated list from the allowed
    vocabulary (falls back to the keyword tagger on any failure). extra
    holds the rest of the rule-card (applies_when, check_type) for storage
    /inspection — empty on fallback."""
    try:
        from app.integrations.internal_llm import get_chat_model

        raw = get_chat_model().invoke(_PROMPT.format(section=section or "", text=text[:1500])).content
        card = _parse(raw or "")
        if not card:
            raise ValueError("model did not return the expected JSON")

        scope = [s for s in card.get("scope", []) if isinstance(s, str) and s in SCOPES]
        if not scope:
            scope = ["global"]  # keep the chunk; just broadly-scoped

        extra = {
            # False only when the model is confident it's reference/onboarding
            # material, so a parse hiccup never wrongly hides a real rule.
            "is_rule": card.get("is_design_rule", True) is not False,
            "applies_when": str(card.get("applies_when", "")).strip(),
            "check_type": str(card.get("check_type", "")).strip(),
        }
        return sorted(set(scope)), extra
    except Exception:
        logger.warning("LLM scope tagging failed for section %r; falling back to keyword tagger",
                       section, exc_info=True)
        return infer_scopes(section, text), {}
