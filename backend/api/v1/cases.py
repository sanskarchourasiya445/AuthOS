"""Case and review endpoints for /api/v1 backed by PostgreSQL persistence and authenticated actor guards."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.auth.dependencies import (
    get_current_user,
    require_case_access,
    require_reviewer_role,
)
from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.db.models import DocumentChunkModel, DocumentModel
from backend.db.repository import PostgresCaseRepository
from contracts.schemas import (
    AIClaimProposal,
    AgentWorkflowResponse,
    Case,
    CaseResultsResponse,
    ClaimAnalysisResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    ErrorCode,
    FinalizationActionRequest,
    PatientDocumentDetail,
    PatientDocumentSummary,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewPacket,
)

logger = logging.getLogger("authos.api.cases")
router = APIRouter()


def get_repository() -> PostgresCaseRepository:
    """Dependency provider for case repository."""
    return PostgresCaseRepository()


@router.get(
    "/health",
    summary="Health check",
    response_model=dict[str, str],
)
def get_health() -> dict[str, str]:
    return {"status": "ok", "version": "v1"}


@router.get(
    "/cases",
    summary="List synthetic demo cases",
    response_model=list[Case],
)
def list_cases(
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[Case]:
    if user.role == UserRole.ADMIN.value:
        return repo.get_all_cases()
    return repo.get_all_cases(allowed_case_ids=user.cases)


@router.get(
    "/cases/{case_id}",
    summary="Get case details",
    response_model=Case,
)
def get_case(
    case_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    _user: Annotated[AuthenticatedUser, Depends(require_case_access)],
) -> Case:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    return case


@router.get(
    "/cases/{case_id}/results",
    summary="Get criterion results and retry history for a case",
    response_model=CaseResultsResponse,
)
def get_case_results(
    case_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    _user: Annotated[AuthenticatedUser, Depends(require_case_access)],
) -> CaseResultsResponse:
    results = repo.get_results(case_id)
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Results for case '{case_id}' were not found."},
        )
    return results


@router.post(
    "/cases/{case_id}/review",
    summary="Record reviewer annotation or gap disposition",
    response_model=ReviewActionResponse,
)
def submit_review_action(
    case_id: str,
    request: ReviewActionRequest,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    user: Annotated[AuthenticatedUser, Depends(require_case_access)],
    _reviewer: Annotated[AuthenticatedUser, Depends(require_reviewer_role)],
) -> ReviewActionResponse:
    actor = f"{user.name} ({user.sub})"
    return repo.record_review(case_id, request, actor=actor)


@router.post(
    "/cases/{case_id}/approve",
    summary="Submit finalization decision (approve, request edits, or reject)",
    response_model=ReviewPacket,
)
def approve_packet(
    case_id: str,
    request: FinalizationActionRequest,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    user: Annotated[AuthenticatedUser, Depends(require_case_access)],
    _reviewer: Annotated[AuthenticatedUser, Depends(require_reviewer_role)],
) -> ReviewPacket:
    actor = f"{user.name} ({user.sub})"
    return repo.finalize_packet(case_id, request, actor=actor)


@router.get(
    "/cases/{case_id}/packet",
    summary="Retrieve review packet",
    response_model=ReviewPacket,
)
def get_review_packet(
    case_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    _user: Annotated[AuthenticatedUser, Depends(require_case_access)],
    preview: Annotated[bool, Query(description="Allow retrieving unfinalized draft packet")] = False,
) -> ReviewPacket:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    packet = repo.get_packet(case_id)
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Packet for case '{case_id}' was not found."},
        )
    if not packet.finalized and not preview:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": ErrorCode.PACKET_NOT_FINALIZED.value,
                "message": "Packet has not been finalized by a human reviewer. Pass ?preview=true to view unfinalized draft.",
            },
        )
    return packet


@router.post(
    "/cases/{case_id}/evaluate",
    summary="Trigger deterministic retrieval and evidence verification for a case",
    response_model=ReviewPacket,
)
def evaluate_case_endpoint(
    case_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    _user: Annotated[AuthenticatedUser, Depends(require_case_access)],
) -> ReviewPacket:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    with repo._session_factory() as session:
        try:
            from backend.workflow.evaluator import evaluate_case
            packet = evaluate_case(case_id, session)
            session.commit()
            return packet
        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error("Internal error evaluating case %s: %s", case_id, type(e).__name__, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": f"An unexpected internal error occurred while evaluating case '{case_id}'.",
                },
            )


@router.post(
    "/cases/{case_id}/documents",
    summary="Safely ingest a patient chart document for a case",
    response_model=DocumentIngestResponse,
)
def ingest_document_endpoint(
    case_id: str,
    request: DocumentIngestRequest,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    user: Annotated[AuthenticatedUser, Depends(require_case_access)],
    _reviewer: Annotated[AuthenticatedUser, Depends(require_reviewer_role)],
) -> DocumentIngestResponse:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    with repo._session_factory() as session:
        try:
            from backend.ingest.service import ingest_document_safe
            actor = f"{user.name} ({user.sub})"
            resp = ingest_document_safe(
                session,
                request,
                expected_patient_id=case.patient_id,
                actor=actor,
                case_id=case_id,
            )
            session.commit()
            return resp
        except ValueError as exc:
            session.rollback()
            msg = str(exc)
            err_code = ErrorCode.VALIDATION_ERROR.value
            if "Cross-patient" in msg or "cannot be reassigned" in msg:
                err_code = ErrorCode.ACCESS_DENIED.value
            elif "Unsupported document format" in msg:
                err_code = ErrorCode.INVALID_DOCUMENT_FORMAT.value
            elif "maximum allowed size" in msg:
                err_code = ErrorCode.DOCUMENT_SIZE_EXCEEDED.value
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": err_code, "message": msg},
            )
        except Exception as e:
            session.rollback()
            logger.error("Error ingesting document for case %s: %s", case_id, type(e).__name__, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": ErrorCode.INTERNAL_ERROR.value, "message": "Failed to ingest document."},
            )


@router.post(
    "/cases/{case_id}/claim-analysis",
    summary="Trigger advisory AI-assisted claim analysis for a case",
    response_model=ClaimAnalysisResponse,
)
def claim_analysis_endpoint(
    case_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    user: Annotated[AuthenticatedUser, Depends(require_case_access)],
    mode: str = Query("deterministic", description="Execution mode: 'deterministic' or 'agent'"),
) -> ClaimAnalysisResponse:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    with repo._session_factory() as session:
        try:
            if mode == "agent":
                from backend.agent.orchestrator import AgentOrchestrator
                orchestrator = AgentOrchestrator()
                agent_resp = orchestrator.run_case_workflow(session, case_id=case_id, actor_name=user.name)
                session.commit()
                # Map agent proposals to standard ClaimAnalysisResponse
                proposals = [
                    AIClaimProposal(
                        criterion_id=p.criterion_id,
                        proposed_status=p.proposed_status,
                        confidence=p.confidence,
                        evidence_quotes=p.evidence_quotes,
                        missing_facts=p.missing_facts,
                        detected_gaps=p.detected_gaps,
                        uncertainty_rationale=p.uncertainty_rationale,
                        is_ai_generated=True,
                        flags=p.flags + ["AGENT_ORCHESTRATED", f"VERIFIED_BY_GATE:{p.is_verified_by_boundary}"],
                    )
                    for p in agent_resp.proposals
                ]
                return ClaimAnalysisResponse(
                    case_id=case_id,
                    patient_id=case.patient_id,
                    policy_id=case.policy_id,
                    analyzer_provider=f"MULTI_AGENT_WORKFLOW ({agent_resp.execution_metadata.provider})",
                    proposals=proposals,
                    disclaimer=agent_resp.disclaimer,
                    generated_at=agent_resp.created_at,
                )
            else:
                from backend.analysis.service import DeterministicClaimAnalyzer
                analyzer = DeterministicClaimAnalyzer()
                response = analyzer.analyze_claims(session, case_id=case_id)
                session.commit()
                return response
        except ValueError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": ErrorCode.CLAIM_ANALYSIS_FAILED.value, "message": str(exc)},
            )
        except Exception as e:
            session.rollback()
            logger.error("Error running claim analysis for case %s: %s", case_id, type(e).__name__, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": ErrorCode.INTERNAL_ERROR.value, "message": "Failed to run claim analysis."},
            )


@router.post(
    "/cases/{case_id}/agent-workflow",
    summary="Trigger bounded multi-agent evidence retrieval and criterion analysis",
    response_model=AgentWorkflowResponse,
)
def agent_workflow_endpoint(
    case_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    user: Annotated[AuthenticatedUser, Depends(require_case_access)],
) -> AgentWorkflowResponse:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    with repo._session_factory() as session:
        try:
            from backend.agent.orchestrator import AgentOrchestrator
            orchestrator = AgentOrchestrator()
            response = orchestrator.run_case_workflow(session, case_id=case_id, actor_name=user.name)
            session.commit()
            return response
        except ValueError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": ErrorCode.CLAIM_ANALYSIS_FAILED.value, "message": str(exc)},
            )
        except Exception as e:
            session.rollback()
            logger.error("Error running agent workflow for case %s: %s", case_id, type(e).__name__, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": ErrorCode.INTERNAL_ERROR.value, "message": "Failed to run agent workflow."},
            )


@router.get(
    "/cases/{case_id}/documents",
    summary="List patient documents for a case",
    response_model=list[PatientDocumentSummary],
)
def list_case_documents(
    case_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    _user: Annotated[AuthenticatedUser, Depends(require_case_access)],
) -> list[PatientDocumentSummary]:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    with repo._session_factory() as session:
        docs = (
            session.query(DocumentModel)
            .filter_by(patient_id=case.patient_id)
            .order_by(DocumentModel.doc_date.desc(), DocumentModel.created_at.desc())
            .all()
        )
        summaries: list[PatientDocumentSummary] = []
        for doc in docs:
            chunk_cnt = (
                session.query(DocumentChunkModel)
                .filter_by(source_id=doc.source_id)
                .count()
            )
            summaries.append(
                PatientDocumentSummary(
                    source_id=doc.source_id,
                    patient_id=doc.patient_id,
                    doc_date=doc.doc_date,
                    character_count=len(doc.text),
                    chunks_count=chunk_cnt,
                    created_at=doc.created_at.isoformat(),
                )
            )
        return summaries


@router.get(
    "/cases/{case_id}/documents/{source_id}",
    summary="Retrieve full raw patient document by source_id with patient isolation",
    response_model=PatientDocumentDetail,
)
def get_case_document(
    case_id: str,
    source_id: str,
    repo: Annotated[PostgresCaseRepository, Depends(get_repository)],
    _user: Annotated[AuthenticatedUser, Depends(require_case_access)],
) -> PatientDocumentDetail:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    with repo._session_factory() as session:
        doc = session.query(DocumentModel).filter_by(source_id=source_id).first()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": ErrorCode.VALIDATION_ERROR.value, "message": f"Document '{source_id}' was not found."},
            )
        if doc.patient_id != case.patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": ErrorCode.ACCESS_DENIED.value,
                    "message": f"Access denied: Document does not belong to case patient.",
                },
            )
        chunk_cnt = (
            session.query(DocumentChunkModel)
            .filter_by(source_id=doc.source_id)
            .count()
        )
        return PatientDocumentDetail(
            source_id=doc.source_id,
            patient_id=doc.patient_id,
            doc_date=doc.doc_date,
            text=doc.text,
            character_count=len(doc.text),
            chunks_count=chunk_cnt,
            created_at=doc.created_at.isoformat(),
        )


