"""Durable PostgreSQL-backed repository for AuthOS cases, criteria, and audit logs."""
from datetime import datetime, timezone
from typing import Callable
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.db.models import (
    AuditLogModel,
    CaseModel,
    CriterionResultModel,
    PolicyCriterionModel,
)
from backend.db.session import SessionLocal
from contracts.schemas import (
    Case,
    CaseResultsResponse,
    CaseStatus,
    CriterionResult,
    ErrorCode,
    FinalizationActionRequest,
    FinalizationActionType,
    PacketCriterionRow,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewPacket,
)


class PostgresCaseRepository:
    """Production-grade relational repository enforcing atomic transactions and row locking."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal):
        self._session_factory = session_factory

    def get_all_cases(self) -> list[Case]:
        with self._session_factory() as session:
            rows = session.query(CaseModel).order_by(CaseModel.case_id).all()
            return [
                Case(
                    case_id=r.case_id,
                    patient_id=r.patient_id,
                    service=r.service,
                    policy_id=r.policy_id,
                    status=CaseStatus(r.status),
                    scenario=r.scenario,
                    created_at=r.created_at.isoformat(),
                )
                for r in rows
            ]

    def get_case(self, case_id: str) -> Case | None:
        with self._session_factory() as session:
            r = session.query(CaseModel).filter_by(case_id=case_id).first()
            if not r:
                return None
            return Case(
                case_id=r.case_id,
                patient_id=r.patient_id,
                service=r.service,
                policy_id=r.policy_id,
                status=CaseStatus(r.status),
                scenario=r.scenario,
                created_at=r.created_at.isoformat(),
            )

    def get_results(self, case_id: str) -> CaseResultsResponse | None:
        with self._session_factory() as session:
            case = session.query(CaseModel).filter_by(case_id=case_id).first()
            if not case:
                return None

            crit_rows = (
                session.query(CriterionResultModel)
                .filter_by(case_id=case_id)
                .order_by(CriterionResultModel.criterion_id)
                .all()
            )

            criteria_results = [
                CriterionResult(
                    criterion_id=cr.criterion_id,
                    status=cr.status,
                    verified=cr.verified,
                    reason=cr.reason,
                    evidence=cr.evidence,
                    missing_facts=cr.missing_facts,
                    retry_log=cr.retry_log,
                    validator_flags=cr.validator_flags,
                )
                for cr in crit_rows
            ]

            return CaseResultsResponse(
                case_id=case.case_id,
                patient_id=case.patient_id,
                service=case.service,
                policy_id=case.policy_id,
                status=CaseStatus(case.status),
                scenario=case.scenario,
                criteria_results=criteria_results,
            )

    def record_review(
        self,
        case_id: str,
        request: ReviewActionRequest,
        actor: str = "HUMAN_REVIEWER (UNAUTHENTICATED_DEV)",
    ) -> ReviewActionResponse:
        session = self._session_factory()
        try:
            # Row lock to prevent race conditions during review
            case = (
                session.query(CaseModel)
                .filter_by(case_id=case_id)
                .with_for_update()
                .first()
            )
            if not case:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
                )

            # Only permit reviewing cases that have completed evaluation
            if case.status not in (CaseStatus.RESULTS_READY.value, CaseStatus.IN_HUMAN_REVIEW.value):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": ErrorCode.INVALID_STATE_TRANSITION.value,
                        "message": f"Cannot submit review actions for case '{case_id}' because it is in status '{case.status}'.",
                    },
                )

            # Verify criterion belongs to policy
            crit_exists = (
                session.query(PolicyCriterionModel)
                .filter_by(policy_id=case.policy_id, criterion_id=request.criterion_id)
                .first()
            )
            if not crit_exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": ErrorCode.VALIDATION_ERROR.value,
                        "message": f"Criterion '{request.criterion_id}' is not part of case '{case_id}'.",
                    },
                )

            # Transition case status if currently RESULTS_READY
            if case.status == CaseStatus.RESULTS_READY.value:
                case.status = CaseStatus.IN_HUMAN_REVIEW.value

            now = datetime.now(timezone.utc)
            audit = AuditLogModel(
                case_id=case_id,
                criterion_id=request.criterion_id,
                action=request.action.value,
                note=request.note,
                actor=actor,
                created_at=now,
            )
            session.add(audit)
            session.commit()

            return ReviewActionResponse(
                case_id=case_id,
                criterion_id=request.criterion_id,
                action=request.action,
                note=request.note,
                recorded_at=now.isoformat(),
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def finalize_packet(
        self,
        case_id: str,
        request: FinalizationActionRequest,
        actor: str = "HUMAN_REVIEWER (UNAUTHENTICATED_DEV)",
    ) -> ReviewPacket:
        session = self._session_factory()
        try:
            # Row lock to prevent concurrent double-approvals
            case = (
                session.query(CaseModel)
                .filter_by(case_id=case_id)
                .with_for_update()
                .first()
            )
            if not case:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
                )

            # Only permit finalization or rejection for cases that have completed evaluation
            if case.status not in (CaseStatus.RESULTS_READY.value, CaseStatus.IN_HUMAN_REVIEW.value):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": ErrorCode.INVALID_STATE_TRANSITION.value,
                        "message": f"Cannot finalize packet for case '{case_id}' in status '{case.status}'. Case must be evaluated first.",
                    },
                )

            now = datetime.now(timezone.utc)
            if request.action == FinalizationActionType.APPROVE_PACKET:
                case.status = CaseStatus.FINALIZED.value
                case.finalized_at = now
                case.reviewer_note = request.reviewer_note
                action_str = "approve_packet"
            elif request.action == FinalizationActionType.REJECT_PACKET:
                case.status = CaseStatus.REJECTED.value
                case.reviewer_note = f"REJECTED: {request.reviewer_note}"
                action_str = "reject_packet"
            elif request.action == FinalizationActionType.REQUEST_EDITS:
                case.status = CaseStatus.IN_HUMAN_REVIEW.value
                case.reviewer_note = f"EDITS_REQUESTED: {request.reviewer_note}"
                action_str = "request_edits"

            audit = AuditLogModel(
                case_id=case_id,
                criterion_id=None,
                action=action_str,
                note=request.reviewer_note,
                actor=actor,
                created_at=now,
            )
            session.add(audit)
            session.commit()

            return self._build_packet_from_case(case, session)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_packet(self, case_id: str) -> ReviewPacket | None:
        with self._session_factory() as session:
            case = session.query(CaseModel).filter_by(case_id=case_id).first()
            if not case:
                return None
            return self._build_packet_from_case(case, session)

    def _build_packet_from_case(self, case: CaseModel, session: Session) -> ReviewPacket:
        results = (
            session.query(CriterionResultModel)
            .filter_by(case_id=case.case_id)
            .order_by(CriterionResultModel.criterion_id)
            .all()
        )

        crit_map = {
            pc.criterion_id: pc.text
            for pc in session.query(PolicyCriterionModel).filter_by(policy_id=case.policy_id).all()
        }

        audits = (
            session.query(AuditLogModel)
            .filter_by(case_id=case.case_id)
            .order_by(AuditLogModel.created_at.asc())
            .all()
        )
        audit_events = [
            {
                "id": a.id,
                "action": a.action,
                "criterion_id": a.criterion_id,
                "note": a.note,
                "actor": a.actor,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in audits
        ]

        rows = [
            PacketCriterionRow(
                criterion_id=r.criterion_id,
                criterion=crit_map.get(r.criterion_id, f"Policy requirement {r.criterion_id}"),
                status=r.status,
                evidence=r.evidence or [],
                conflicting_evidence=getattr(r, "conflicting_evidence", []) or [],
                missing_facts=r.missing_facts or [],
                validator_flags=r.validator_flags or [],
                verification_version="deterministic-v1",
                reason=r.reason or "",
                review_required=(r.status != "MET"),
            )
            for r in results
        ]

        # Determine canonical generated_at from the latest evaluation completion audit event
        eval_audit = next((a for a in reversed(audits) if a.action == "CASE_EVALUATION_COMPLETED"), None)
        canonical_generated_at = eval_audit.created_at.isoformat() if (eval_audit and eval_audit.created_at) else None

        finalized = (case.status == CaseStatus.FINALIZED.value)
        return ReviewPacket(
            case_id=case.case_id,
            patient_id=case.patient_id,
            policy_id=case.policy_id,
            packet_type="SYNTHETIC_DEMO_REVIEW_PACKET",
            decision_authority="HUMAN_REVIEWER",
            criteria=rows,
            disclaimer="Preparation aid only. Not a medical-necessity or coverage decision.",
            finalized=finalized,
            finalized_at=case.finalized_at.isoformat() if case.finalized_at else None,
            reviewer_note=case.reviewer_note,
            generated_at=canonical_generated_at,
            audit_events=audit_events,
        )
