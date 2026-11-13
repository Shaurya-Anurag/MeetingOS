"""Deterministic structural and provenance validation for generated intelligence."""
from __future__ import annotations

from typing import Any

REQUIRED_LISTS = (
    "topics", "decisions", "action_items", "risks_and_concerns",
    "unresolved_questions", "contradictions",
)


def validate_intelligence_payload(payload: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("Intelligence payload must be an object.")
    normalized = dict(payload)
    warnings: list[str] = []
    for key in REQUIRED_LISTS:
        value = normalized.get(key, [])
        if not isinstance(value, list):
            warnings.append(f"{key} was not a list and was replaced with an empty list.")
            value = []
        clean = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                warnings.append(f"{key}[{index}] was not an object and was skipped.")
                continue
            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                warnings.append(f"{key}[{index}].evidence was malformed.")
                evidence = []
            item = dict(item)
            item["evidence"] = [entry for entry in evidence if isinstance(entry, dict) and str(entry.get("text") or "").strip()]
            clean.append(item)
        normalized[key] = clean
    normalized["executive_summary"] = str(normalized.get("executive_summary") or "").strip()
    return normalized, warnings


def verify_claim_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Mark records with no supporting spans as unsupported; never fabricate evidence."""
    result = dict(payload)
    for key in REQUIRED_LISTS:
        updated = []
        for item in result.get(key, []):
            item = dict(item)
            evidence = item.get("evidence", [])
            item["support_status"] = "supported" if evidence and all(
                entry.get("verification_status") == "verified" for entry in evidence
            ) else "needs_review"
            updated.append(item)
        result[key] = updated
    return result
