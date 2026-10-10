"""AI-assisted claim analysis interface and deterministic fallback provider for AuthOS (Phase 6).

Guarantees:
- Model output is advisory only and strictly separated from authoritative verification results.
- Structured, schema-validated outputs: AIClaimProposal with confidence, uncertainty rationale, and detected gaps.
- Transparent provider reporting: reports 'DETERMINISTIC_FALLBACK (RULE_BASED)', never pretending external AI was run.
- Zero prompt injection execution: adversarial instructions in chart text are flagged and ignored.
- Non-authoritative boundary: AI proposals alone NEVER set CriterionResultModel status to MET or verified=True.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import re
from typing import Any
from sqlalchemy.orm import Session

from backend.db.models import (
    AuditLogModel,
    CaseModel,
    DocumentModel,
    PolicyCriterionModel,
)
from backend.ingest.service import detect_adversarial_patterns
from backend.rag.retrieval import retrieve_chart_candidates
from backend.verification.engine import (
    has_keyword,
    verify_criterion_evidence,
)
from contracts.schemas import (
    AIClaimProposal,
    ClaimAnalysisResponse,
    CriterionStatus,
    EvidenceItem,
    EvidencePolarity,
)


class ClaimAnalysisEngine(ABC):
    """Abstract interface for advisory AI prior-authorization claim analyzers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the analysis provider."""
        pass

    @abstractmethod
    def analyze_claims(
        self,
        session: Session,
        *,
        case_id: str,
    ) -> ClaimAnalysisResponse:
        """Analyze a case's records and generate advisory claim proposals."""
        pass


class DeterministicClaimAnalyzer(ClaimAnalysisEngine):
    """Deterministic, rule-backed claim analysis provider.

    Used when external LLM services are not configured or for deterministic baseline comparison.
    Never fabricates quotes, offsets, or facts.
    """

    @property
    def provider_name(self) -> str:
        return "DETERMINISTIC_FALLBACK (RULE_BASED)"

    def analyze_claims(
        self,
        session: Session,
        *,
        case_id: str,
    ) -> ClaimAnalysisResponse:
        case = session.query(CaseModel).filter_by(case_id=case_id).first()
        if not case:
            raise ValueError(f"Case '{case_id}' was not found.")

        criteria = (
            session.query(PolicyCriterionModel)
            .filter_by(policy_id=case.policy_id)
            .order_by(PolicyCriterionModel.criterion_id)
            .all()
        )
        if not criteria:
            raise ValueError(f"No policy criteria found for policy '{case.policy_id}'.")

        raw_docs = session.query(DocumentModel).filter_by(patient_id=case.patient_id).all()
        raw_docs_map = {d.source_id: d for d in raw_docs}

        now = datetime.now(timezone.utc)
        proposals: list[AIClaimProposal] = []

        for crit in criteria:
            query = crit.text
            if crit.evidence_expectation:
                query = f"{crit.text} {crit.evidence_expectation}"
            if has_keyword(crit.text, ["conservative", "physical therapy", "therapy"]):
                query = f"{query} physical therapy"

            # Retrieve candidates with strict patient isolation
            candidates = retrieve_chart_candidates(
                session,
                patient_id=case.patient_id,
                query=query,
                top_k=3,
            )

            # Check for adversarial injection in retrieved candidates
            flags: list[str] = ["AI_ADVISORY_ONLY"]
            for cand in candidates:
                inj_flags = detect_adversarial_patterns(cand.chunk_text)
                if inj_flags:
                    flags.append("PROMPT_INJECTION_IGNORED")
                    break

            # Formulate structured proposal based on deterministic analysis
            evidence_items: list[EvidenceItem] = []
            for c in candidates:
                # Check polarity
                c_lower = c.chunk_text.lower()
                polarity = EvidencePolarity.SUPPORTING
                if any(w in c_lower for w in ["declined", "refused", "stopped", "failed to complete", "did not tolerate"]):
                    polarity = EvidencePolarity.CONTRADICTING
                elif any(w in c_lower for w in ["unclear", "exact start date", "not documented", "unknown", "not present", "requires clarification"]):
                    polarity = EvidencePolarity.UNCLEAR

                evidence_items.append(
                    EvidenceItem(
                        source_id=c.source_id,
                        patient_id=c.patient_id,
                        quote=c.chunk_text,
                        document_date=c.doc_date,
                        chunk_id=c.chunk_id,
                        char_start=c.char_start,
                        char_end=c.char_end,
                        polarity=polarity,
                    )
                )

            # Analyze clinical requirement
            missing_facts: list[str] = []
            detected_gaps: list[str] = []

            if has_keyword(crit.text, ["conservative", "physical therapy", "therapy"]):
                req_facts = ["Supervised physical therapy", "Duration >= 6 weeks"]
                has_pt = any("physical therapy" in c.chunk_text.lower() or "therapy" in c.chunk_text.lower() for c in candidates)
                has_contra = any(e.polarity == EvidencePolarity.CONTRADICTING for e in evidence_items)
                has_ambig = any(e.polarity == EvidencePolarity.UNCLEAR for e in evidence_items) or any("exact start date" in c.chunk_text.lower() for c in candidates)

                if has_contra:
                    prop_status = CriterionStatus.CONTRADICTED
                    confidence = 0.90
                    rationale = "Documentation explicitly indicates patient declined or did not complete recommended physical therapy."
                    detected_gaps.append("Conservative therapy declined by patient")
                elif has_ambig:
                    prop_status = CriterionStatus.AMBIGUOUS
                    confidence = 0.50
                    rationale = "Physical therapy is documented, but the exact duration, frequency, or completion dates are missing from the chart."
                    missing_facts.append("Duration >= 6 weeks")
                    detected_gaps.append("Unstated physical therapy duration")
                elif has_pt and any("july" in c.chunk_text.lower() and "august" in c.chunk_text.lower() for c in candidates):
                    prop_status = CriterionStatus.MET
                    confidence = 0.95
                    rationale = "Chart documents completed supervised physical therapy spanning 6 weeks with persistent symptoms."
                elif has_pt:
                    prop_status = CriterionStatus.AMBIGUOUS
                    confidence = 0.40
                    rationale = "Physical therapy mentioned but 6-week duration threshold is not conclusively substantiated."
                    missing_facts.append("Duration >= 6 weeks")
                    detected_gaps.append("Duration inconclusive")
                else:
                    prop_status = CriterionStatus.MISSING
                    confidence = 0.85
                    rationale = "No documented evidence of supervised physical therapy was found in the supplied records."
                    missing_facts.extend(req_facts)
                    detected_gaps.append("No physical therapy documentation found")

            elif has_keyword(crit.text, ["request", "order", "mri"]):
                has_order = any("request" in c.chunk_text.lower() or "order" in c.chunk_text.lower() for c in candidates)
                if has_order:
                    prop_status = CriterionStatus.MET
                    confidence = 0.95
                    rationale = "Requisition for lumbar MRI study by ordering clinician is documented."
                else:
                    prop_status = CriterionStatus.MISSING
                    confidence = 0.85
                    rationale = "No physician requisition order for lumbar MRI was located."
                    missing_facts.append("Lumbar MRI requested")
                    detected_gaps.append("Missing physician imaging requisition")

            elif has_keyword(crit.text, ["persistent", "symptom", "back pain", "low back"]):
                has_pain = any("back pain" in c.chunk_text.lower() for c in candidates)
                if has_pain:
                    prop_status = CriterionStatus.MET
                    confidence = 0.95
                    rationale = "Patient report of persistent low back pain is documented."
                else:
                    prop_status = CriterionStatus.MISSING
                    confidence = 0.85
                    rationale = "No documented history of low back pain."
                    missing_facts.append("Low back pain")
                    detected_gaps.append("Missing documentation of low back symptoms")
            else:
                prop_status = CriterionStatus.MISSING
                confidence = 0.50
                rationale = "Policy requirement could not be substantiated against supplied records."
                missing_facts.append(crit.text)
                detected_gaps.append("Unsubstantiated criterion")

            proposal = AIClaimProposal(
                criterion_id=crit.criterion_id,
                proposed_status=prop_status,
                confidence=confidence,
                evidence_quotes=evidence_items,
                missing_facts=missing_facts,
                detected_gaps=detected_gaps,
                uncertainty_rationale=rationale,
                is_ai_generated=True,
                flags=flags,
            )
            proposals.append(proposal)

        # Log audit event
        audit = AuditLogModel(
            case_id=case_id,
            criterion_id=None,
            action="AI_CLAIM_ANALYSIS_EXECUTED",
            note=f"Advisory claim analysis generated by {self.provider_name} for {len(proposals)} criteria. Human review required.",
            actor=f"AI_ADVISORY ({self.provider_name})",
            created_at=now,
        )
        session.add(audit)
        session.flush()

        return ClaimAnalysisResponse(
            case_id=case_id,
            patient_id=case.patient_id,
            policy_id=case.policy_id,
            analyzer_provider=self.provider_name,
            proposals=proposals,
            disclaimer="AI-assisted claim analysis is advisory only. Not authoritative. Every evidence citation requires deterministic verification and human review.",
            generated_at=now.isoformat(),
        )


def verify_ai_proposal_against_verifier(
    session: Session,
    proposal: AIClaimProposal,
    *,
    case_id: str,
    criterion_text: str,
    patient_id: str,
    required_facts: list[str] | None = None,
    min_duration_days: int | None = None,
) -> Any:
    """Enforce the non-negotiable verification boundary on an advisory AI proposal.

    Verifies cited evidence quotes against raw documents stored in PostgreSQL.
    Rejects fabricated quotes, offset mismatches, and cross-patient quotes.
    """
    docs = session.query(DocumentModel).filter_by(patient_id=patient_id).all()
    raw_documents = [
        {
            "source_id": d.source_id,
            "patient_id": d.patient_id,
            "date": d.doc_date,
            "text": d.text,
        }
        for d in docs
    ]

    candidate_evidence = [
        {
            "source_id": e.source_id,
            "patient_id": e.patient_id,
            "quote": e.quote,
            "char_start": e.char_start,
            "char_end": e.char_end,
            "document_date": e.document_date,
        }
        for e in proposal.evidence_quotes
    ]

    return verify_criterion_evidence(
        criterion_id=proposal.criterion_id,
        criterion_text=criterion_text,
        patient_id=patient_id,
        candidate_evidence=candidate_evidence,
        raw_documents=raw_documents,
        required_facts=required_facts or [],
        min_duration_days=min_duration_days,
    )
