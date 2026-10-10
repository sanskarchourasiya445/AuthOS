"""Criterion Analysis Agent for AuthOS bounded multi-agent workflow (Phase 8).

Responsibilities:
- Evaluate retrieved clinical candidates against policy criterion requirements.
- Distinguish supportive, contradictory, ambiguous, and missing evidence.
- Distinguish explicit clinical refusal from plans, recommendations, or pending events.
- Never convert absence of documentation into proof of a negative occurrence.
- Formulate structured advisory proposals with exact source citations and uncertainty rationales.
- Transparent provider identification: explicitly reports whether execution used deterministic stubs or real LLM.
"""
from dataclasses import dataclass
import logging
from typing import Any

from backend.verification.engine import has_keyword
from contracts.schemas import (
    AgentCriterionProposal,
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


class CriterionAnalysisAgent:
    """Agent role responsible for clinical evidence synthesis and proposal generation."""

    def __init__(self, provider_name: str = "DETERMINISTIC_AGENT_STUB", is_external_llm: bool = False):
        self.provider_name = provider_name
        self.is_external_llm = is_external_llm

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

        # Case 1: Empty evidence (explicit abstention)
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

        # Convert candidate dicts to EvidenceItem models with validation
        evidence_items: list[EvidenceItem] = []
        for c in candidates:
            pol_str = c.get("polarity", EvidencePolarity.SUPPORTING.value)
            try:
                pol = EvidencePolarity(pol_str)
            except ValueError:
                pol = EvidencePolarity.SUPPORTING

            evidence_items.append(
                EvidenceItem(
                    source_id=c["source_id"],
                    patient_id=c["patient_id"],
                    quote=c["quote"],
                    document_date=c.get("document_date"),
                    chunk_id=c.get("chunk_id"),
                    char_start=c.get("char_start"),
                    char_end=c.get("char_end"),
                    polarity=pol,
                    retrieval_round=retrieval_round,
                )
            )

        # Evaluate clinical logic
        missing_facts: list[str] = []
        detected_gaps: list[str] = []
        c_texts = [c["quote"].lower() for c in candidates]
        has_contra = any(e.polarity == EvidencePolarity.CONTRADICTING for e in evidence_items)
        has_unclear = any(e.polarity == EvidencePolarity.UNCLEAR for e in evidence_items)

        # A. Conservative Therapy / Physical Therapy criterion
        if has_keyword(criterion_text, ["conservative", "physical therapy", "therapy"]):
            req_defaults = ["Supervised physical therapy", "Duration >= 6 weeks"]
            active_reqs = required_facts or req_defaults

            # Distinguish explicit refusal vs plan vs completed
            is_refusal = any(
                w in text for text in c_texts
                for w in ["declined", "refused", "stopped", "failed to complete", "did not tolerate"]
            )
            is_plan_only = any(
                w in text for text in c_texts
                for w in ["plan to initiate", "referred for future", "pending consultation", "recommend physical therapy"]
            ) and not any(
                w in text for text in c_texts
                for w in ["completed", "attended", "weeks of therapy", "sessions"]
            )
            has_dates_span = any(
                ("july" in text and "august" in text) or ("6 weeks" in text) or ("8 weeks" in text)
                for text in c_texts
            )

            if is_refusal:
                status = CriterionStatus.CONTRADICTED
                confidence = 0.95
                rationale = (
                    "Chart documentation contains explicit patient refusal or intolerance of prescribed conservative physical therapy. "
                    "This directly contradicts conservative therapy completion requirements."
                )
                detected_gaps.append("Patient declined or discontinued conservative therapy.")
            elif is_plan_only:
                status = CriterionStatus.AMBIGUOUS
                confidence = 0.65
                rationale = (
                    "Physical therapy is recommended or planned in clinical notes, but completed course is not documented. "
                    "A planned recommendation cannot substitute for completed trial."
                )
                missing_facts.append("Duration >= 6 weeks")
                detected_gaps.append("Physical therapy is planned/recommended but not completed.")
            elif has_unclear or any("exact start date" in text for text in c_texts):
                status = CriterionStatus.AMBIGUOUS
                confidence = 0.50
                rationale = (
                    "Physical therapy is mentioned, but exact onset dates, weekly frequency, or duration threshold are ambiguous."
                )
                missing_facts.append("Duration >= 6 weeks")
                detected_gaps.append("Ambiguous physical therapy duration/completion.")
            elif has_dates_span:
                status = CriterionStatus.MET
                confidence = 0.95
                rationale = (
                    "Chart substantiates completed course of supervised physical therapy spanning required duration "
                    "with documented persistent symptoms."
                )
            else:
                status = CriterionStatus.AMBIGUOUS
                confidence = 0.45
                rationale = "Physical therapy participation is noted, but 6-week duration threshold is not conclusively established."
                missing_facts.append("Duration >= 6 weeks")
                detected_gaps.append("Duration inconclusive from provided records.")

        # B. Imaging Requisition / Order criterion
        elif has_keyword(criterion_text, ["request", "order", "mri"]):
            has_order = any("request" in text or "order" in text or "requisition" in text for text in c_texts)
            if has_order:
                status = CriterionStatus.MET
                confidence = 0.95
                rationale = "Physician order and requisition for advanced lumbar MRI imaging is documented."
            else:
                status = CriterionStatus.MISSING
                confidence = 0.85
                rationale = "No physician order or requisition for requested imaging located in patient chart."
                missing_facts.append("Lumbar MRI requested")
                detected_gaps.append("Missing physician imaging requisition order.")

        # C. Persistent Symptom / Low Back Pain criterion
        elif has_keyword(criterion_text, ["persistent", "symptom", "back pain", "low back"]):
            has_pain = any("back pain" in text or "lumbago" in text or "lumbar pain" in text for text in c_texts)
            if has_pain:
                status = CriterionStatus.MET
                confidence = 0.95
                rationale = "Documentation of persistent low back symptoms confirmed by clinical exam/history."
            else:
                status = CriterionStatus.MISSING
                confidence = 0.85
                rationale = "No clinical documentation of low back symptoms found."
                missing_facts.append("Low back pain")
                detected_gaps.append("Missing documentation of low back symptoms.")

        # D. Generic / Fallback criterion
        else:
            status = CriterionStatus.MISSING
            confidence = 0.50
            rationale = "Criterion could not be substantiated from retrieved passages."
            missing_facts.append(criterion_text)
            detected_gaps.append("Unsubstantiated criterion requirement.")

        return AnalysisAgentResult(
            criterion_id=criterion_id,
            proposed_status=status,
            confidence=confidence,
            evidence_items=evidence_items,
            missing_facts=missing_facts,
            detected_gaps=detected_gaps,
            uncertainty_rationale=rationale,
            is_external_llm=self.is_external_llm,
            provider_name=self.provider_name,
            flags=flags,
        )
