from typing import Any, Literal
from pydantic import BaseModel, Field


# ---------- validate_oas / fix_oas ----------

class OASInput(BaseModel):
    oas_content: str = Field(..., description="Raw OAS document (YAML or JSON) as text")
    format: Literal["yaml", "json"] = "yaml"
    api_name: str | None = None


class GuidelineViolation(BaseModel):
    rule_id: str
    message: str
    path: str = ""                       # location inside the OAS
    severity: Literal["error", "warning", "info"] = "warning"
    # One of: "spectral-core" (generic OpenAPI best-practice rules from
    # Spectral's built-in spectral:oas ruleset), "custom-ruleset" (Org-specific
    # rules defined in api-ruleset.yaml's own rules: section), or "rag"
    # (prose guidance retrieved from the Guidelines Index, not a Spectral
    # finding). Kept as a plain str (not a Literal) so a stale/older value
    # never hard-fails GuidelineViolation construction.
    source: str = "spectral-core"
    rule_explanation: str | None = None  # enriched from the ruleset lookup dict
    suggested_fix: str | None = None
    # Citation — always None for source="spectral-core" (generic OpenAPI
    # rules aren't tied to any Org doc). Set for "rag" from the retrieved
    # chunk's metadata, and for "custom-ruleset" from that rule's
    # x-guideline-section in api-ruleset.yaml — both point at the same
    # underlying doc/section-naming convention either way.
    source_document: str | None = None   # e.g. "API-Design-Guidelines.docx"
    source_section: str | None = None    # e.g. "6. Authentication and Authorization"
    # For custom-ruleset findings only: the actual guideline prose from the
    # section this rule enforces, fetched by exact section match — so the
    # finding carries the "why" text, not just a pointer to it.
    guideline_excerpt: str | None = None


class ValidateOASResult(BaseModel):
    is_valid: bool
    violations: list[GuidelineViolation]
    summary: str
    next_step: str       # what the caller should do next, given this result
    guidelines_toc: str  # table of contents of the guidelines corpus — call get_guideline_section for full text
    # Whole-corpus digest of every design/security rule, built once at
    # ingestion (SCOPE_TAGGER=llm) — complements the per-element violations/
    # notes above, which only surface the top-K nearest guideline chunks per
    # OAS element and can miss a rule that's real but didn't score close
    # enough. None if it hasn't been generated (SCOPE_TAGGER=keyword, or
    # nothing ingested yet).
    guidelines_summary: str | None = None


class FixOASResult(BaseModel):
    mechanical_fixes: list[GuidelineViolation]   # ruleset defines a suggested_fix — apply as-is
    needs_judgment: list[GuidelineViolation]      # no suggested_fix — decide using rule_explanation
    guideline_notes: list[GuidelineViolation]     # prose context from the Guidelines Index
    summary: str
    next_step: str       # what the caller should do next, given this result
    guidelines_toc: str  # table of contents of the guidelines corpus — call get_guideline_section for full text
    guidelines_summary: str | None = None  # see ValidateOASResult.guidelines_summary


# ---------- get_guideline_section ----------

class GuidelineSectionInput(BaseModel):
    section: str = Field(..., description="Section name or fragment, e.g. '4. Idempotency' or just 'idempotency'")
    document: str | None = Field(None, description="Restrict to one source document filename (from guidelines_toc)")


class GuidelineSection(BaseModel):
    document: str
    section: str
    content: str


class GetGuidelineSectionResult(BaseModel):
    matches: list[GuidelineSection]
    summary: str
    next_step: str


# ---------- search_api_registry ----------

class SearchRegistryInput(BaseModel):
    query: str = Field(..., description="Natural-language description of the endpoint/spec needed")
    top_k: int = 5
    api_id: str | None = Field(None, description="Restrict results to one API (from search_api_referential)")


class RegistryHit(BaseModel):
    api_id: str
    api_name: str
    endpoint: str | None = None      # e.g. "POST /documents"; None for spec-summary chunks
    chunk_type: Literal["oas_operation", "oas_summary"]
    content: str
    score: float
    source_document: str | None = None  # e.g. "payments-api.yaml" — citation


class SearchRegistryResult(BaseModel):
    hits: list[RegistryHit]
    summary: str
    next_step: str  # what the caller should do next, given this result


# ---------- search_api_referential ----------

class SearchReferentialInput(BaseModel):
    query: str = Field(..., description="What the user needs an API for, in natural language")
    top_k: int = 5


class ReferentialHit(BaseModel):
    api_id: str
    api_name: str
    description: str
    url: str | None = None
    score: float
    source_document: str | None = None  # e.g. "api-referential.yaml" — citation


class SearchReferentialResult(BaseModel):
    hits: list[ReferentialHit]
    summary: str
    next_step: str  # what the caller should do next, given this result
