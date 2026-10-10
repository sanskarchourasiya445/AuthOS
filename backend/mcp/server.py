"""AuthOS Outward-Facing Model Context Protocol (MCP) Server.

Exposes strictly read-only, patient-isolated, deterministic evidence-linting
tools to external AI assistants (e.g. Claude Desktop, clinical copilot).

Safety & Security Invariants:
1. Purely Deterministic: Tool outputs come exclusively from AuthOS's deterministic
   verifier and relational repository. External clients cannot override statuses.
2. Read-Only Boundary: Zero approval, packet mutation, deletion, or SQL query tools.
3. Patient Chart Isolation: All document and case queries enforce actor scoping and
   reject cross-patient record access.
4. Grounded Provenance: Returns verbatim quotes with verified character offsets.
"""
import json
import logging
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session

from backend.db.models import CaseModel, DocumentChunkModel, DocumentModel
from backend.db.repository import PostgresCaseRepository
from backend.db.session import SessionLocal
from backend.mcp.auth import (
    MCPAccessDeniedError,
    MCPAuthenticationError,
    get_authenticated_actor,
    verify_actor_case_access,
)
from backend.workflow.evaluator import evaluate_case
from contracts.schemas import CaseStatus, CriterionStatus


class _StderrStreamHandler(logging.StreamHandler):
    """StreamHandler that dynamically routes diagnostic records to sys.stderr."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, val):
        pass


def _configure_mcp_logging() -> None:
    """Ensure MCP diagnostic logging streams exclusively to stderr to protect stdio JSON-RPC transport."""
    mcp_logger = logging.getLogger("authos.mcp")
    if not any(isinstance(h, _StderrStreamHandler) for h in mcp_logger.handlers):
        handler = _StderrStreamHandler()
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
        )
        mcp_logger.addHandler(handler)
    mcp_logger.propagate = False


_configure_mcp_logging()
logger = logging.getLogger("authos.mcp.server")

# Instantiate official MCP Server
server = MCPServer(
    name="authos-evidence-linter",
    instructions=(
        "AuthOS Prior-Authorization Pre-Submission Evidence Linter. "
        "Provides read-only access to clinical prior-authorization cases, deterministic "
        "evidence verification, documentation gap analysis, and verbatim citation inspection."
    ),
    version="1.0.0",
)


def _format_error(error_code: str, message: str) -> str:
    """Format safe structured JSON error response."""
    return json.dumps({
        "status": "error",
        "error_code": error_code,
        "message": message,
    }, indent=2)


@server.tool(
    name="authos_list_cases",
    description="List clinical prior-authorization cases accessible to the authenticated actor.",
)
def authos_list_cases(auth_token: str | None = None) -> str:
    """List prior-authorization cases for the authorized user.

    Args:
        auth_token: Optional Bearer JWT string. If omitted, uses ambient AUTHOS_MCP_TOKEN.
    """
    try:
        actor = get_authenticated_actor(auth_token)
        repo = PostgresCaseRepository()
        allowed = None if actor.role == "admin" else actor.cases
        cases = repo.get_all_cases(allowed_case_ids=allowed)

        payload = {
            "status": "success",
            "actor": {
                "sub": actor.sub,
                "name": actor.name,
                "role": actor.role,
            },
            "total_cases": len(cases),
            "cases": [
                {
                    "case_id": c.case_id,
                    "patient_id": c.patient_id,
                    "service": c.service,
                    "policy_id": c.policy_id,
                    "status": c.status.value if isinstance(c.status, CaseStatus) else str(c.status),
                    "scenario": c.scenario,
                    "created_at": c.created_at,
                }
                for c in cases
            ],
        }
        return json.dumps(payload, indent=2)
    except MCPAuthenticationError as exc:
        return _format_error("AUTHENTICATION_REQUIRED", str(exc))
    except Exception as exc:
        logger.error("Error in authos_list_cases: %s", exc, exc_info=True)
        return _format_error("INTERNAL_ERROR", "Failed to retrieve case list.")


@server.tool(
    name="authos_get_case",
    description="Retrieve clinical and policy details for an authorized prior-authorization case.",
)
def authos_get_case(case_id: str, auth_token: str | None = None) -> str:
    """Retrieve details of a single case if caller is authorized.

    Args:
        case_id: Case identifier (e.g. 'CASE-SYN-001')
        auth_token: Optional Bearer JWT string.
    """
    try:
        actor = get_authenticated_actor(auth_token)
        verify_actor_case_access(actor, case_id)

        repo = PostgresCaseRepository()
        case = repo.get_case(case_id)
        if not case:
            return _format_error("CASE_NOT_FOUND", f"Case '{case_id}' was not found.")

        payload = {
            "status": "success",
            "case": {
                "case_id": case.case_id,
                "patient_id": case.patient_id,
                "service": case.service,
                "policy_id": case.policy_id,
                "status": case.status.value if isinstance(case.status, CaseStatus) else str(case.status),
                "scenario": case.scenario,
                "created_at": case.created_at,
            },
            "authorized_actor": actor.sub,
        }
        return json.dumps(payload, indent=2)
    except MCPAuthenticationError as exc:
        return _format_error("AUTHENTICATION_REQUIRED", str(exc))
    except MCPAccessDeniedError as exc:
        return _format_error("ACCESS_DENIED", str(exc))
    except Exception as exc:
        logger.error("Error in authos_get_case: %s", exc, exc_info=True)
        return _format_error("INTERNAL_ERROR", f"Failed to retrieve case '{case_id}'.")


@server.tool(
    name="authos_lint_evidence",
    description=(
        "Run deterministic clinical evidence verification on patient records for a case. "
        "Evaluates payer policy requirements against the patient's chart, identifies documentation "
        "gaps and contradictory notes, and verifies character offsets without external LLM authority."
    ),
)
def authos_lint_evidence(case_id: str, auth_token: str | None = None) -> str:
    """Execute authoritative deterministic evidence verification for a case.

    Args:
        case_id: Case identifier (e.g. 'CASE-SYN-001')
        auth_token: Optional Bearer JWT string.
    """
    try:
        actor = get_authenticated_actor(auth_token)
        verify_actor_case_access(actor, case_id)

        with SessionLocal() as session:
            case = session.query(CaseModel).filter_by(case_id=case_id).first()
            if not case:
                return _format_error("CASE_NOT_FOUND", f"Case '{case_id}' was not found.")

            packet = evaluate_case(case_id, session)
            session.commit()

            criteria_summary = []
            for cr in packet.criteria:
                status_str = cr.status.value if isinstance(cr.status, CriterionStatus) else str(cr.status)
                criteria_summary.append({
                    "criterion_id": cr.criterion_id,
                    "criterion_text": cr.criterion,
                    "status": status_str,
                    "verified": (status_str == "MET"),
                    "reason": cr.reason,
                    "missing_facts": cr.missing_facts or [],
                    "evidence_citations": [
                        {
                            "source_id": ev.source_id,
                            "patient_id": ev.patient_id,
                            "quote": ev.quote,
                            "char_start": ev.char_start,
                            "char_end": ev.char_end,
                            "document_date": ev.document_date,
                            "polarity": ev.polarity.value if hasattr(ev.polarity, "value") else str(ev.polarity),
                        }
                        for ev in (cr.evidence or [])
                    ],
                    "conflicting_evidence": [
                        {
                            "source_id": ev.source_id,
                            "quote": ev.quote,
                            "char_start": ev.char_start,
                            "char_end": ev.char_end,
                        }
                        for ev in (cr.conflicting_evidence or [])
                    ],
                    "validator_flags": cr.validator_flags or [],
                })

            payload = {
                "status": "success",
                "case_id": packet.case_id,
                "patient_id": packet.patient_id,
                "service": case.service,
                "policy_id": packet.policy_id or case.policy_id,
                "case_workflow_status": case.status,
                "criteria_results": criteria_summary,
                "verification_mode": "DETERMINISTIC_RULES_ENGINE",
                "authority_notice": "Determinations are established solely by the deterministic verification engine. Human clinician review is required for finalization.",
                "audited_by": f"{actor.name} ({actor.sub})",
            }
            return json.dumps(payload, indent=2)
    except MCPAuthenticationError as exc:
        return _format_error("AUTHENTICATION_REQUIRED", str(exc))
    except MCPAccessDeniedError as exc:
        return _format_error("ACCESS_DENIED", str(exc))
    except Exception as exc:
        logger.error("Error in authos_lint_evidence: %s", exc, exc_info=True)
        return _format_error("INTERNAL_ERROR", f"Failed to execute evidence linting on case '{case_id}'.")


@server.tool(
    name="authos_get_document_excerpt",
    description=(
        "Retrieve verbatim document text or verified passage by source_id. "
        "Enforces strict patient chart boundaries and verifies character offset slices."
    ),
)
def authos_get_document_excerpt(
    case_id: str,
    source_id: str,
    char_start: int | None = None,
    char_end: int | None = None,
    auth_token: str | None = None,
) -> str:
    """Retrieve patient document content with verbatim boundary enforcement.

    Args:
        case_id: Case identifier to scope patient boundary
        source_id: Document identifier (e.g. 'SYN-P001-NOTE-01')
        char_start: Optional exact start character offset
        char_end: Optional exact end character offset
        auth_token: Optional Bearer JWT string
    """
    try:
        actor = get_authenticated_actor(auth_token)
        verify_actor_case_access(actor, case_id)

        with SessionLocal() as session:
            case = session.query(CaseModel).filter_by(case_id=case_id).first()
            if not case:
                return _format_error("CASE_NOT_FOUND", f"Case '{case_id}' was not found.")

            doc = session.query(DocumentModel).filter_by(source_id=source_id).first()
            if not doc:
                return _format_error("DOCUMENT_NOT_FOUND", f"Document '{source_id}' was not found.")

            # Strict patient boundary isolation check
            if doc.patient_id != case.patient_id:
                logger.warning(
                    "SECURITY: Cross-patient document access attempt. Case patient '%s' != Doc patient '%s'",
                    case.patient_id,
                    doc.patient_id,
                )
                return _format_error(
                    "CROSS_PATIENT_ACCESS_DENIED",
                    f"Access Denied: Document '{source_id}' does not belong to patient of case '{case_id}'.",
                )

            raw_text = doc.text or ""
            total_len = len(raw_text)

            # Offset slice verification
            if char_start is not None and char_end is not None:
                if not (0 <= char_start < char_end <= total_len):
                    return _format_error(
                        "INVALID_OFFSETS",
                        f"Offsets [{char_start}:{char_end}] exceed document length ({total_len} characters).",
                    )
                excerpt = raw_text[char_start:char_end]
                payload = {
                    "status": "success",
                    "source_id": doc.source_id,
                    "patient_id": doc.patient_id,
                    "document_date": doc.doc_date,
                    "char_start": char_start,
                    "char_end": char_end,
                    "excerpt": excerpt,
                    "document_total_length": total_len,
                    "verified_verbatim": True,
                }
            else:
                payload = {
                    "status": "success",
                    "source_id": doc.source_id,
                    "patient_id": doc.patient_id,
                    "document_date": doc.doc_date,
                    "full_text": raw_text,
                    "document_total_length": total_len,
                }

            return json.dumps(payload, indent=2)
    except MCPAuthenticationError as exc:
        return _format_error("AUTHENTICATION_REQUIRED", str(exc))
    except MCPAccessDeniedError as exc:
        return _format_error("ACCESS_DENIED", str(exc))
    except Exception as exc:
        logger.error("Error in authos_get_document_excerpt: %s", exc, exc_info=True)
        return _format_error("INTERNAL_ERROR", "Failed to retrieve document excerpt.")


def main() -> None:
    """Run MCP server over standard input/output (stdio)."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
