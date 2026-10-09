"""End-to-end deterministic evaluation workflow for AuthOS cases.

Connects:
1. Payer policy criteria from PostgreSQL.
2. Patient chart candidate retrieval via BM25 (patient-isolated).
3. Deterministic evidence provenance validation and polarity assessment.
4. Factual sufficiency and contradiction arbitration.
5. Persistent PostgreSQL storage of results and audit trails.
6. Deterministic review packet rendering for human review.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.db.models import (
    AuditLogModel,
    CaseModel,
    CriterionResultModel,
    DocumentModel,
    PolicyCriterionModel,
)
from backend.db.repository import PostgresCaseRepository
from backend.rag.retrieval import retrieve_chart_candidates
from backend.verification.engine import verify_criterion_evidence
from contracts.schemas import CaseStatus, CriterionStatus, ReviewPacket


def evaluate_case(case_id: str, session: Session) -> ReviewPacket:
    """Execute end-to-end evidence retrieval, verification, and packet generation for a case."""
    case = session.query(CaseModel).filter_by(case_id=case_id).first()
    if not case:
        raise ValueError(f"Case '{case_id}' was not found.")

    # 1. Fetch policy criteria
    criteria = (
        session.query(PolicyCriterionModel)
        .filter_by(policy_id=case.policy_id)
        .order_by(PolicyCriterionModel.criterion_id)
        .all()
    )
    if not criteria:
        raise ValueError(f"No policy criteria found for policy '{case.policy_id}'.")

    # 2. Fetch raw patient documents for provenance verification
    docs = session.query(DocumentModel).filter_by(patient_id=case.patient_id).all()
    raw_documents = [
        {
            "source_id": d.source_id,
            "patient_id": d.patient_id,
            "date": d.doc_date,
            "text": d.text,
        }
        for d in docs
    ]

    all_results = []
    # 3. Process each criterion through candidate retrieval and deterministic verification
    for crit in criteria:
        # Formulate query from policy criterion text and expectation
        query = crit.text
        if crit.evidence_expectation:
            query = f"{crit.text} {crit.evidence_expectation}"

        # Retrieve chart candidates with strict patient isolation
        candidates_raw = retrieve_chart_candidates(
            session,
            patient_id=case.patient_id,
            query=query,
            top_k=5,
        )

        candidate_items = [
            {
                "source_id": c.source_id,
                "patient_id": c.patient_id,
                "quote": c.chunk_text,
                "chunk_id": c.chunk_id,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "document_date": c.doc_date,
            }
            for c in candidates_raw
        ]

        # Determine clinical policy parameters using word boundaries
        from backend.verification.engine import has_keyword
        if has_keyword(crit.text, ["conservative", "physical therapy", "therapy"]):
            min_duration = 42
            req_facts = ["Supervised physical therapy", "Duration >= 6 weeks"]
        elif has_keyword(crit.text, ["request", "order", "mri"]):
            min_duration = None
            req_facts = ["Lumbar MRI requested"]
        elif has_keyword(crit.text, ["persistent", "symptom", "back pain", "low back"]):
            min_duration = None
            req_facts = ["Low back pain"]
        else:
            min_duration = None
            req_facts = []

        # Run deterministic evidence verification
        crit_eval = verify_criterion_evidence(
            criterion_id=crit.criterion_id,
            criterion_text=crit.text,
            patient_id=case.patient_id,
            candidate_evidence=candidate_items,
            raw_documents=raw_documents,
            required_facts=req_facts,
            min_duration_days=min_duration,
        )
        all_results.append(crit_eval)

        # 4. Persist or update CriterionResultModel in PostgreSQL
        res_record = (
            session.query(CriterionResultModel)
            .filter_by(case_id=case_id, criterion_id=crit.criterion_id)
            .first()
        )
        if not res_record:
            res_record = CriterionResultModel(
                case_id=case_id,
                criterion_id=crit.criterion_id,
                status=crit_eval.status.value,
                verified=crit_eval.verified,
                reason=crit_eval.reason,
                evidence=[e.model_dump() for e in crit_eval.evidence],
                conflicting_evidence=[e.model_dump() for e in crit_eval.conflicting_evidence],
                missing_facts=crit_eval.missing_facts,
                validator_flags=crit_eval.validator_flags,
                retry_log=[],
            )
            session.add(res_record)
        else:
            res_record.status = crit_eval.status.value
            res_record.verified = crit_eval.verified
            res_record.reason = crit_eval.reason
            res_record.evidence = [e.model_dump() for e in crit_eval.evidence]
            res_record.conflicting_evidence = [e.model_dump() for e in crit_eval.conflicting_evidence]
            res_record.missing_facts = crit_eval.missing_facts
            res_record.validator_flags = crit_eval.validator_flags

    # 5. Record evaluation audit event
    has_non_met = any(r.status != CriterionStatus.MET for r in all_results)
    now = datetime.now(timezone.utc)
    audit = AuditLogModel(
        case_id=case_id,
        criterion_id=None,
        action="CASE_EVALUATION_COMPLETED",
        note=(
            f"Deterministic evaluation completed for {len(criteria)} criteria. "
            f"Statuses: {', '.join(f'{r.criterion_id}:{r.status.value}' for r in all_results)}. "
            f"Human review {'required' if has_non_met else 'optional'}."
        ),
        actor="SYSTEM_VERIFIER (DETERMINISTIC_ENGINE)",
        created_at=now,
    )
    session.add(audit)

    # 6. Update case status based on evaluation outcome
    if case.status in (CaseStatus.DRAFT.value, CaseStatus.RUNNING.value, CaseStatus.RESULTS_READY.value, CaseStatus.IN_HUMAN_REVIEW.value):
        if has_non_met:
            case.status = CaseStatus.IN_HUMAN_REVIEW.value
        else:
            case.status = CaseStatus.RESULTS_READY.value

    session.flush()

    repo = PostgresCaseRepository(session_factory=lambda: session)
    return repo._build_packet_from_case(case, session)
