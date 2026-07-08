"""
fix_oas — self-contained: runs Spectral itself (fresh findings), retrieves
guideline context, asks the internal LLM to rewrite the OAS, then re-runs
Spectral on the OUTPUT to report what remains unresolved.
"""
import json
import logging
import re

from app.models import OASInput, FixOASResult
from app.integrations.spectral import run_spectral
from app.integrations.internal_llm import get_chat_model
from app.tools.validate_oas import guideline_context

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMResponseError(RuntimeError):
    """The rewrite model didn't return the expected JSON shape."""


def _parse_llm_json(raw: str) -> dict:
    """Best-effort parse: try as-is, then strip markdown fences (a common
    deviation from "no markdown fences" instructions) before giving up."""
    for candidate in (raw, _FENCE_RE.sub("", raw).strip()):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if "fixed_oas" not in parsed:
            break
        return parsed
    logger.error("fix_oas: model returned unparseable/incomplete JSON: %s", raw[:500])
    raise LLMResponseError("The rewrite model did not return the expected JSON output")


TOOL_DESCRIPTION = (
    "Fix an OpenAPI spec so it complies with API Design Guidelines. "
    "Returns the corrected spec, the list of changes made, and any "
    "violations that could not be auto-fixed."
)

_PROMPT = """You are fixing an OpenAPI spec to comply with API Design Guidelines.

Spectral findings (each with explanation and suggested fix where available):
{findings}

Relevant guideline excerpts from the knowledge base:
{context}

Original OAS ({fmt}):
---
{oas}
---

Rules:
- Change ONLY what a listed finding or guideline requires.
- Do not rename resources or alter semantics that would break existing consumers;
  if a fix would do that, leave it and note it instead.

Respond with EXACTLY this JSON (no markdown fences):
{{"fixed_oas": "<the full corrected spec as a string>", "changes": ["<change 1>", "..."]}}
"""


def fix_oas(payload: OASInput) -> FixOASResult:
    findings = run_spectral(payload.oas_content, payload.format)
    notes = guideline_context(payload.oas_content)

    findings_text = "\n".join(
        f"- [{v.severity}] {v.rule_id} at {v.path}: {v.message}"
        + (f" | why: {v.rule_explanation}" if v.rule_explanation else "")
        + (f" | fix: {v.suggested_fix}" if v.suggested_fix else "")
        for v in findings
    ) or "None"
    context_text = "\n".join(f"- {n.message}" for n in notes) or "None"

    llm = get_chat_model()
    raw = llm.invoke(_PROMPT.format(
        findings=findings_text, context=context_text,
        oas=payload.oas_content, fmt=payload.format,
    )).content
    parsed = _parse_llm_json(raw)
    fixed, changes = parsed["fixed_oas"], parsed.get("changes", [])

    remaining = run_spectral(fixed, payload.format)  # verify our own work
    return FixOASResult(
        fixed_oas_content=fixed,
        changes_made=changes,
        unresolved_violations=remaining,
        summary=f"{len(changes)} change(s) applied; {len(remaining)} finding(s) remain.",
    )
