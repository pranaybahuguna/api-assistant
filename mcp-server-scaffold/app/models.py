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
    source: Literal["spectral", "rag"] = "spectral"
    rule_explanation: str | None = None  # enriched from the ruleset lookup dict
    suggested_fix: str | None = None


class ValidateOASResult(BaseModel):
    is_valid: bool
    violations: list[GuidelineViolation]
    summary: str


class FixOASResult(BaseModel):
    fixed_oas_content: str
    changes_made: list[str]
    unresolved_violations: list[GuidelineViolation]
    summary: str


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


class SearchRegistryResult(BaseModel):
    hits: list[RegistryHit]
    summary: str


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


class SearchReferentialResult(BaseModel):
    hits: list[ReferentialHit]
    summary: str
