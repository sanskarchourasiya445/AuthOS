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
from backend.db.repository import PostgresCaseRepository
from contracts.schemas import (
    Case,
    CaseResultsResponse,
    ErrorCode,
    FinalizationActionRequest,
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
    all_cases = repo.get_all_cases()
    if user.role == UserRole.ADMIN.value or "*" in user.cases:
        return all_cases
    return [c for c in all_cases if c.case_id in user.cases]


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
