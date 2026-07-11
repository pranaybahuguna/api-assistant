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
    # "spectral-core": generic OpenAPI best-practice rules from Spectral's
    #   built-in `spectral:oas` ruleset (extends: in api-ruleset.yaml).
    # "custom-ruleset": Org-specific rules defined in api-ruleset.yaml's
    #   own `rules:` section (mechanically enforced, each has an x-fix).
    # "rag": prose guidance retrieved from the Guidelines Index — not a
    #   Spectral finding at all.
    source: Literal["spectral-core", "custom-ruleset", "rag"] = "spectral-core"
    rule_explanation: str | None = None  # enriched from the ruleset lookup dict
    suggested_fix: str | None = None
    # Citation — only set for source="rag" entries, since spectral-core/
    # custom-ruleset ones come from the ruleset file/rule_id, not a retrieved chunk.
    source_document: str | None = None   # e.g. "API-Design-Guidelines.docx"
    source_section: str | None = None    # e.g. "6. Authentication and Authorization"


class ValidateOASResult(BaseModel):
    is_valid: bool
    violations: list[GuidelineViolation]
    summary: str
    next_step: str  # what the caller should do next, given this result


class FixOASResult(BaseModel):
    mechanical_fixes: list[GuidelineViolation]   # ruleset defines a suggested_fix — apply as-is
    needs_judgment: list[GuidelineViolation]      # no suggested_fix — decide using rule_explanation
    guideline_notes: list[GuidelineViolation]     # prose context from the Guidelines Index
    summary: str
    next_step: str  # what the caller should do next, given this result


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
