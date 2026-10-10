"""Evidence Retrieval Agent for AuthOS bounded multi-agent workflow (Phase 8).

Responsibilities:
- Identify potentially relevant chart passages for a supplied policy criterion.
- Enforce strict patient isolation: cross-patient queries are rejected immediately.
- Formulate targeted, grounded search queries using criterion text and missing-fact hints.
- Use patient-scoped retrieval backed by PostgreSQL document chunks.
- Never invent quotations, chunk IDs, or source document references.
- Clearly abstain when no relevant evidence exists in the patient chart.
- Flag prompt injection attempts detected in retrieved clinical passages.
"""
from dataclasses import dataclass
import logging
from typing import Any
from sqlalchemy.orm import Session

from backend.db.models import DocumentModel
from backend.ingest.service import detect_adversarial_patterns
from backend.rag.retrieval import retrieve_chart_candidates
from contracts.schemas import EvidenceItem, EvidencePolarity

logger = logging.getLogger("authos.agent.retrieval")


@dataclass
class RetrievalAgentResult:
    """Structured response from the Evidence Retrieval Agent."""
    criterion_id: str
    patient_id: str
    query_used: str
    candidates: list[dict[str, Any]]
    abstained: bool
    relevance_explanations: list[str]
    flags: list[str]


class EvidenceRetrievalAgent:
    """Agent role responsible for grounded clinical candidate retrieval."""

    def __init__(self, top_k: int = 4):
        self.top_k = top_k

    def retrieve(
        self,
        session: Session,
        *,
        criterion_id: str,
        criterion_text: str,
        patient_id: str,
        target_patient_id: str,
        evidence_expectation: str | None = None,
        missing_facts: list[str] | None = None,
        retry_round: int = 1,
    ) -> RetrievalAgentResult:
        """Execute patient-scoped evidence retrieval with explicit safety boundaries."""
        # 1. Patient boundary invariant check
        if not patient_id or not target_patient_id:
            raise ValueError("Patient identifiers must be non-empty.")
        if patient_id != target_patient_id:
            logger.error(
                "Cross-patient retrieval attempt blocked: query patient=%s, target patient=%s",
                patient_id,
                target_patient_id,
            )
            return RetrievalAgentResult(
                criterion_id=criterion_id,
                patient_id=patient_id,
                query_used="BLOCKED_CROSS_PATIENT",
                candidates=[],
                abstained=True,
                relevance_explanations=["Blocked cross-patient retrieval attempt."],
                flags=["CROSS_PATIENT_VIOLATION_BLOCKED"],
            )

        # 2. Formulate targeted search query
        query_parts = [criterion_text]
        if evidence_expectation:
            query_parts.append(evidence_expectation)
        if missing_facts:
            # Query reformulation for bounded corrective round
            for fact in missing_facts:
                query_parts.append(fact)

        query = " ".join(query_parts)

        # 3. Patient-scoped chart retrieval
        raw_candidates = retrieve_chart_candidates(
            session,
            patient_id=patient_id,
            query=query,
            top_k=self.top_k,
            corrective=False,  # Agent handles orchestration of corrective rounds
        )

        flags: list[str] = []
        if not raw_candidates:
            return RetrievalAgentResult(
                criterion_id=criterion_id,
                patient_id=patient_id,
                query_used=query,
                candidates=[],
                abstained=True,
                relevance_explanations=["No matching chart documentation found for criterion."],
                flags=["NO_EVIDENCE_FOUND", "ABSTAINED"],
            )

        # 4. Check for adversarial injection in retrieved candidates
        candidates_out: list[dict[str, Any]] = []
        explanations: list[str] = []

        for cand in raw_candidates:
            # Check prompt injection
            inj_flags = detect_adversarial_patterns(cand.chunk_text)
            if inj_flags:
                flags.append("PROMPT_INJECTION_DETECTED_IN_CHART")
                flags.extend(inj_flags)

            # Polarity heuristic for agent candidate assessment
            c_lower = cand.chunk_text.lower()
            polarity = EvidencePolarity.SUPPORTING.value
            if any(w in c_lower for w in ["declined", "refused", "stopped", "failed to complete", "did not tolerate"]):
                polarity = EvidencePolarity.CONTRADICTING.value
                explanations.append(f"Candidate {cand.chunk_id} exhibits contradicting/refusal clinical polarity.")
            elif any(w in c_lower for w in ["unclear", "exact start date", "not documented", "unknown"]):
                polarity = EvidencePolarity.UNCLEAR.value
                explanations.append(f"Candidate {cand.chunk_id} exhibits ambiguous documentation.")
            else:
                explanations.append(f"Candidate {cand.chunk_id} provides relevant clinical context.")

            candidates_out.append(
                {
                    "source_id": cand.source_id,
                    "patient_id": cand.patient_id,
                    "quote": cand.chunk_text,
                    "document_date": cand.doc_date,
                    "chunk_id": cand.chunk_id,
                    "char_start": cand.char_start,
                    "char_end": cand.char_end,
                    "polarity": polarity,
                    "retrieval_round": retry_round,
                }
            )

        return RetrievalAgentResult(
            criterion_id=criterion_id,
            patient_id=patient_id,
            query_used=query,
            candidates=candidates_out,
            abstained=False,
            relevance_explanations=explanations,
            flags=list(set(flags)),
        )
