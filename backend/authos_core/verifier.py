"""Deterministic checks for claims against synthetic chart source spans.

This module checks provenance and exact quote existence. It deliberately does not
claim that a quote semantically proves a clinical criterion; that judgment must
be separately reviewed and is outside this deterministic verifier's guarantees.
"""
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class VerificationResult:
    claim_id: str
    accepted: bool
    reasons: list[str]
    source_id: str | None = None
    patient_id: str | None = None
    quote: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_claim(claim: dict[str, Any], *, patient_id: str,
                 source_documents: list[dict[str, Any]]) -> VerificationResult:
    """Check patient match, source existence, and exact quote containment.

    `accepted` means provenance checks passed, not that the evidence entails the
    claim. Callers must keep that distinction visible in UI and output schemas.
    """
    claim_id = str(claim.get("claim_id", "UNIDENTIFIED"))
    source_id = claim.get("source_id")
    quote = claim.get("quote")
    reasons: list[str] = []
    if not isinstance(source_id, str) or not source_id.strip():
        reasons.append("SOURCE_ID_MISSING")
    if not isinstance(quote, str) or not quote.strip():
        reasons.append("QUOTE_MISSING")
    source = next((d for d in source_documents if d.get("source_id") == source_id), None)
    if source is None and source_id:
        reasons.append("SOURCE_NOT_FOUND")
    if source is not None:
        if source.get("patient_id") != patient_id:
            reasons.append("PATIENT_MISMATCH")
        if isinstance(quote, str) and quote.strip():
            text = source.get("text", "")
            if quote not in text:
                reasons.append("QUOTE_NOT_VERBATIM")
    return VerificationResult(
        claim_id=claim_id,
        accepted=not reasons,
        reasons=reasons,
        source_id=source_id if isinstance(source_id, str) else None,
        patient_id=patient_id,
        quote=quote if isinstance(quote, str) else None,
    )


def render_review_packet(*, case_id: str, patient_id: str,
                         criterion_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Render a deterministic packet; no LLM authors the final packet prose."""
    rows = []
    for item in criterion_results:
        rows.append({
            "criterion_id": item["criterion_id"],
            "criterion": item["criterion"],
            "status": item["status"],
            "evidence": item.get("verified_evidence", []),
            "reason": item.get("reason", ""),
            "review_required": item["status"] != "MET",
        })
    return {
        "case_id": case_id,
        "patient_id": patient_id,
        "packet_type": "SYNTHETIC_DEMO_REVIEW_PACKET",
        "decision_authority": "HUMAN_REVIEWER",
        "criteria": rows,
        "disclaimer": "Preparation aid only. Not a medical-necessity or coverage decision.",
        "finalized": False,
    }
