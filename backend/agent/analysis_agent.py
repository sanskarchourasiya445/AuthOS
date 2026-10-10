"""Criterion Analysis Agent for AuthOS bounded multi-agent workflow (Phase 8 & 11).

Responsibilities:
- Evaluate retrieved clinical candidates against policy criterion requirements.
- Uses pluggable BaseLLMProvider (Gemini hosted provider or deterministic stub).
- Enforces strict evidence grounding and citation provenance validation before accepting proposals.
- Distinguishes supportive, contradictory, ambiguous, and missing evidence.
- Never converts absence of documentation into proof of a negative occurrence.
- Formulates structured advisory proposals with exact source citations and uncertainty rationales.
- Transparent provider identification: explicitly reports provider and external LLM status.
"""
from dataclasses import dataclass
import logging
from typing import Any

from backend.agent.llm_provider import (
    BaseLLMProvider,
    LLMCriterionProposal,
    LLMProviderResult,
    get_llm_provider,
)
from backend.config import settings
from contracts.schemas import (
    CriterionStatus,
    EvidenceItem,
    EvidencePolarity,
)

logger = logging.getLogger("authos.agent.analysis")


@dataclass
class AnalysisAgentResult:
    """Structured response from the Criterion Analysis Agent."""
    criterion_id: str
    proposed_status: CriterionStatus
    confidence: float
    evidence_items: list[EvidenceItem]
    missing_facts: list[str]
    detected_gaps: list[str]
    uncertainty_rationale: str
    is_external_llm: bool
    provider_name: str
    flags: list[str]


def validate_and_ground_evidence(
    proposal: LLMCriterionProposal,
    candidates: list[dict[str, Any]],
    patient_id: str,
    retrieval_round: int = 1,
) -> tuple[list[EvidenceItem], list[str], CriterionStatus]:
    """Validate model citations against retrieved candidate chunks.

    Enforces:
    1. Cited source_id must exist in supplied candidates.
    2. Cited patient_id must match authorized scoped patient.
    3. Quoted text must be an exact verbatim substring of the candidate chunk text.
    4. Exact character start and end offsets are computed from the verified candidate chunk.
    5. Fabricated sources, altered quotes, or cross-patient references are rejected.
    6. If all evidence for a proposed MET is rejected, the status is safely downgraded.
    """
    valid_items: list[EvidenceItem] = []
    flags: list[str] = []

    # Map candidate chunks by source_id
    cand_by_source: dict[str, dict[str, Any]] = {c["source_id"]: c for c in candidates if "source_id" in c}

    for q in proposal.evidence_quotes:
        source_id = q.source_id.strip() if q.source_id else ""
        raw_quote = q.quote.strip() if q.quote else ""

        # 1. Source existence check
        if source_id not in cand_by_source:
            flags.append(f"UNKNOWN_SOURCE_ID_REJECTED:{source_id}")
            continue

        cand = cand_by_source[source_id]

        # 2. Patient boundary check
        cand_patient = cand.get("patient_id")
        if cand_patient != patient_id:
            flags.append(f"CROSS_PATIENT_QUOTE_REJECTED:{cand_patient}")
            continue

        # 3. Verbatim quotation match check
        cand_text = cand.get("quote", "")
        sub_idx = cand_text.find(raw_quote)
        if sub_idx == -1:
            flags.append(f"ALTERED_OR_FABRICATED_QUOTE_REJECTED:{source_id}")
            continue

        # 4. Compute verified character offsets
        base_start = cand.get("char_start") or 0
        char_start = base_start + sub_idx
        char_end = char_start + len(raw_quote)

        # 5. Parse polarity
        pol_val = q.polarity.upper() if q.polarity else "SUPPORTING"
        if pol_val in EvidencePolarity.__members__:
            polarity = EvidencePolarity[pol_val]
        else:
            polarity = EvidencePolarity.SUPPORTING

        valid_items.append(
            EvidenceItem(
                source_id=source_id,
                patient_id=patient_id,
                quote=raw_quote,
                document_date=cand.get("document_date"),
                chunk_id=cand.get("chunk_id"),
                char_start=char_start,
                char_end=char_end,
                polarity=polarity,
                retrieval_round=retrieval_round,
            )
        )

    # 6. Parse proposed status safely
    status_str = proposal.proposed_status.upper().strip()
    try:
        proposed_status = CriterionStatus(status_str)
    except ValueError:
        flags.append(f"UNKNOWN_STATUS_FALLBACK:{status_str}")
        proposed_status = CriterionStatus.AMBIGUOUS

    # 7. Safe fallback if proposed MET has no verified supporting evidence
    if proposed_status == CriterionStatus.MET and not valid_items:
        flags.append("UNSUPPORTED_MET_DOWNGRADED_TO_MISSING")
        proposed_status = CriterionStatus.MISSING

    return valid_items, flags, proposed_status


class CriterionAnalysisAgent:
    """Agent role responsible for clinical evidence synthesis and proposal generation."""

    def __init__(
        self,
        provider: BaseLLMProvider | None = None,
        provider_name: str | None = None,
        is_external_llm: bool | None = None,
    ):
        if provider is not None:
            self.provider = provider
        elif provider_name is not None:
            self.provider = get_llm_provider(provider_name=provider_name)
        else:
            self.provider = get_llm_provider()

        self.provider_name = self.provider.provider_name
        self.is_external_llm = self.provider.is_external_llm

    def analyze(
        self,
        *,
        criterion_id: str,
        criterion_text: str,
        patient_id: str,
        required_facts: list[str],
        min_duration_days: int | None,
        candidates: list[dict[str, Any]],
        retrieval_round: int = 1,
    ) -> AnalysisAgentResult:
        """Synthesize candidate evidence into a structured advisory proposal."""
        flags: list[str] = [f"PROVIDER:{self.provider_name}", "ADVISORY_PROPOSAL"]

        # Case 1: Empty evidence (explicit deterministic abstention without calling LLM)
        if not candidates:
            return AnalysisAgentResult(
                criterion_id=criterion_id,
                proposed_status=CriterionStatus.MISSING,
                confidence=0.90,
                evidence_items=[],
                missing_facts=required_facts or [criterion_text],
                detected_gaps=["No clinical documentation found in patient chart."],
                uncertainty_rationale=(
                    "No relevant chart documentation was retrieved. Note: absence of evidence is not proof "
                    "of non-occurrence, but fails the conservative prior authorization substantiation requirement."
                ),
                is_external_llm=self.is_external_llm,
                provider_name=self.provider_name,
                flags=flags + ["EVIDENCE_ABSENT_ABSTAINED"],
            )

        # Case 2: Delegate to configured provider
        provider_res: LLMProviderResult = self.provider.generate_proposal(
            criterion_id=criterion_id,
            criterion_text=criterion_text,
            patient_id=patient_id,
            required_facts=required_facts,
            min_duration_days=min_duration_days,
            candidates=candidates,
        )

        # Case 3: Handle provider failure (fail safely into controlled MISSING state)
        if not provider_res.success or not provider_res.proposal:
            err_code = provider_res.error_code or "PROVIDER_FAILURE"
            err_msg = provider_res.error_message or "Unknown provider failure"
            flags.extend([f"PROVIDER_ERROR:{err_code}", "PROPOSAL_UNAVAILABLE"])

            return AnalysisAgentResult(
                criterion_id=criterion_id,
                proposed_status=CriterionStatus.MISSING,
                confidence=0.0,
                evidence_items=[],
                missing_facts=required_facts or [criterion_text],
                detected_gaps=[f"Analysis unavailable: {err_code}"],
                uncertainty_rationale=f"LLM advisory proposal unavailable ({err_code}): {err_msg}",
                is_external_llm=self.is_external_llm,
                provider_name=self.provider_name,
                flags=flags,
            )

        # Case 4: Validate and ground model citations
        proposal = provider_res.proposal
        evidence_items, grounding_flags, validated_status = validate_and_ground_evidence(
            proposal=proposal,
            candidates=candidates,
            patient_id=patient_id,
            retrieval_round=retrieval_round,
        )
        flags.extend(grounding_flags)

        return AnalysisAgentResult(
            criterion_id=criterion_id,
            proposed_status=validated_status,
            confidence=proposal.confidence,
            evidence_items=evidence_items,
            missing_facts=proposal.missing_facts,
            detected_gaps=proposal.detected_gaps,
            uncertainty_rationale=proposal.uncertainty_rationale,
            is_external_llm=self.is_external_llm,
            provider_name=self.provider_name,
            flags=flags,
        )
