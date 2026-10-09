"""Case and review endpoints for /api/v1."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from contracts.schemas import (
    Case,
    CaseResultsResponse,
    ErrorCode,
    FinalizationActionRequest,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewPacket,
)

router = APIRouter()

FIXTURES_PATH = Path(__file__).resolve().parents[3] / "contracts" / "mock_response.json"


class MockCaseRepository:
    """In-memory mock store initialized from contracts/mock_response.json.

    This provides a deterministic, hermetic repository for Phase 0 contract validation
    without introducing a premature database dependency.
    """

    def __init__(self, path: Path):
        self._path = path
        self._load()

    def _load(self):
        data = json.loads(self._path.read_text(encoding="utf-8"))
        self.cases: dict[str, Case] = {
            c["case_id"]: Case.model_validate(c) for c in data.get("cases", [])
        }
        self.results: dict[str, CaseResultsResponse] = {
            k: CaseResultsResponse.model_validate(v)
            for k, v in data.get("results_by_case", {}).items()
        }
        self.packets: dict[str, ReviewPacket] = {
            k: ReviewPacket.model_validate(v)
            for k, v in data.get("packets_by_case", {}).items()
        }
        self.reviews: list[ReviewActionResponse] = []

    def get_all_cases(self) -> list[Case]:
        return list(self.cases.values())

    def get_case(self, case_id: str) -> Case | None:
        return self.cases.get(case_id)

    def get_results(self, case_id: str) -> CaseResultsResponse | None:
        return self.results.get(case_id)

    def record_review(self, case_id: str, request: ReviewActionRequest) -> ReviewActionResponse:
        record = ReviewActionResponse(
            case_id=case_id,
            criterion_id=request.criterion_id,
            action=request.action,
            note=request.note,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.reviews.append(record)
        return record

    def get_packet(self, case_id: str) -> ReviewPacket | None:
        if case_id in self.packets:
            return self.packets[case_id]
        results = self.results.get(case_id)
        if not results:
            return None
        # Synthesize an unfinalized packet from existing results
        from contracts.schemas import PacketCriterionRow
        rows = [
            PacketCriterionRow(
                criterion_id=r.criterion_id,
                criterion=f"Policy requirement {r.criterion_id}",
                status=r.status,
                evidence=r.evidence,
                reason=r.reason or "",
                review_required=(r.status.value != "MET"),
            )
            for r in results.criteria_results
        ]
        packet = ReviewPacket(
            case_id=case_id,
            patient_id=results.patient_id,
            packet_type="SYNTHETIC_DEMO_REVIEW_PACKET",
            decision_authority="HUMAN_REVIEWER",
            criteria=rows,
            disclaimer="Preparation aid only. Not a medical-necessity or coverage decision.",
            finalized=False,
        )
        self.packets[case_id] = packet
        return packet

    def finalize_packet(self, case_id: str, request: FinalizationActionRequest) -> ReviewPacket:
        packet = self.get_packet(case_id)
        if not packet:
            raise KeyError(case_id)
        packet.finalized = True
        packet.finalized_at = datetime.now(timezone.utc).isoformat()
        packet.reviewer_note = request.reviewer_note
        self.packets[case_id] = packet
        return packet


repo = MockCaseRepository(FIXTURES_PATH)


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
def list_cases() -> list[Case]:
    return repo.get_all_cases()


@router.get(
    "/cases/{case_id}",
    summary="Get case details",
    response_model=Case,
)
def get_case(case_id: str) -> Case:
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
def get_case_results(case_id: str) -> CaseResultsResponse:
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
def submit_review_action(case_id: str, request: ReviewActionRequest) -> ReviewActionResponse:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    return repo.record_review(case_id, request)


@router.post(
    "/cases/{case_id}/approve",
    summary="Submit finalization decision (approve, request edits, or reject)",
    response_model=ReviewPacket,
)
def approve_packet(case_id: str, request: FinalizationActionRequest) -> ReviewPacket:
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.CASE_NOT_FOUND.value, "message": f"Case '{case_id}' was not found."},
        )
    return repo.finalize_packet(case_id, request)


@router.get(
    "/cases/{case_id}/packet",
    summary="Retrieve review packet",
    response_model=ReviewPacket,
)
def get_review_packet(
    case_id: str,
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
