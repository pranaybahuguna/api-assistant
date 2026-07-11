"""
Two things live here, both fed by the SAME ruleset YAML file (which is a
plain file on the server — deliberately NOT vectorized):

1. run_spectral()   — shells out to the Spectral CLI to lint an OAS.
2. get_rule_lookup() — parses the ruleset once at startup into a
   {rule_id: {description, severity, fix}} dict. When a finding comes back
   from Spectral it already carries the exact rule id, so enriching it is
   an O(1) dictionary lookup — no semantic search needed or wanted.
"""
import json
import logging
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import yaml

from app.models import GuidelineViolation

logger = logging.getLogger(__name__)

_SEVERITY_MAP = {0: "error", 1: "warning", 2: "info", 3: "info"}


class SpectralError(RuntimeError):
    """Spectral could not be run or its output could not be parsed —
    distinct from "Spectral ran and found zero violations"."""


@lru_cache
def get_rule_lookup() -> dict[str, dict]:
    """Parse the ruleset file into rule_id -> {description, severity, fix}."""
    path = Path(os.environ.get("SPECTRAL_RULESET_PATH", "./resources/api-ruleset.yaml"))
    if not path.exists():
        return {}
    ruleset = yaml.safe_load(path.read_text()) or {}
    lookup: dict[str, dict] = {}
    for rule_id, rule in (ruleset.get("rules") or {}).items():
        if not isinstance(rule, dict):
            continue
        lookup[rule_id] = {
            "description": rule.get("description", ""),
            "severity": rule.get("severity", "warning"),
            # convention: put remediation guidance in a custom x-fix field
            "fix": rule.get("x-fix", ""),
        }
    return lookup


def enrich(violation: GuidelineViolation) -> GuidelineViolation:
    """Attach the ruleset's own explanation/fix text to a Spectral finding,
    and classify it: a rule_id present in api-ruleset.yaml's own
    `rules:` section is a Org-specific rule ("custom-ruleset"); anything else
    came from Spectral's built-in `spectral:oas` ruleset ("spectral-core")
    — the finding's rule_id is the only signal needed, no guessing."""
    rule = get_rule_lookup().get(violation.rule_id)
    if rule:
        violation.source = "custom-ruleset"
        violation.rule_explanation = rule["description"]
        violation.suggested_fix = rule["fix"] or violation.suggested_fix
    else:
        violation.source = "spectral-core"
    return violation


def run_spectral(oas_content: str, fmt: str = "yaml") -> list[GuidelineViolation]:
    spectral_binary = os.environ.get("SPECTRAL_BINARY", "spectral")
    ruleset_path = os.environ.get("SPECTRAL_RULESET_PATH", "./resources/api-ruleset.yaml")
    suffix = ".yaml" if fmt == "yaml" else ".json"

    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(oas_content)
        tmp = Path(f.name)

    try:
        try:
            result = subprocess.run(
                [spectral_binary, "lint", str(tmp), "--ruleset", ruleset_path, "--format", "json"],
                capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError as e:
            raise SpectralError(
                f"Spectral binary not found at '{spectral_binary}' — is it installed on PATH?"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise SpectralError("Spectral lint timed out after 60s") from e

        # Spectral's own exit codes: 0 = no error-severity findings, 1 = ran
        # and found error-severity findings — both are normal outcomes with
        # JSON on stdout. Anything else with empty stdout means it didn't run.
        if not result.stdout.strip():
            if result.returncode not in (0, 1):
                logger.error("Spectral exited %d with no output; stderr: %s",
                             result.returncode, result.stderr.strip())
                raise SpectralError(f"Spectral failed to run (exit {result.returncode}): "
                                     f"{result.stderr.strip() or 'no error output'}")
            return []

        try:
            findings = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.error("Spectral returned non-JSON output: %s", result.stdout[:500])
            raise SpectralError("Spectral returned output that could not be parsed as JSON") from e

        return [
            # source is set by enrich() below, based on whether rule_id is
            # in the Org ruleset — not worth guessing here first.
            enrich(GuidelineViolation(
                rule_id=item.get("code", "unknown"),
                message=item.get("message", ""),
                path=".".join(str(p) for p in item.get("path", [])),
                severity=_SEVERITY_MAP.get(item.get("severity", 1), "warning"),
            ))
            for item in findings
        ]
    finally:
        tmp.unlink(missing_ok=True)
