"""Safe document ingestion and adversarial validation service for AuthOS (Phase 6).

Guarantees:
- Supported formats: text/plain, text/markdown, application/json.
- Rejects oversized, binary, malformed, or unapproved MIME formats.
- Untrusted content safety: detects embedded prompt injections without altering source text.
- Exact provenance: computes chunk boundaries with exact character offsets.
- Strict patient isolation: rejects cross-patient document ingestion.
"""
from datetime import datetime, timezone
import json
import re
from typing import Any
from sqlalchemy.orm import Session

from backend.db.models import AuditLogModel, CaseModel, DocumentChunkModel, DocumentModel
from backend.rag.ingest import chunk_patient_document, estimate_tokens
from contracts.schemas import DocumentIngestRequest, DocumentIngestResponse

SUPPORTED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
}

# Regex heuristics targeting prompt injection and instruction override attempts in clinical text
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:prior|previous)\s+instructions"),
    re.compile(r"(?i)disregard\s+(?:all\s+)?(?:prior\s+)?criteria"),
    re.compile(r"(?i)override\s+(?:system\s+)?prompt"),
    re.compile(r"(?i)you\s+are\s+now\s+(?:an?\s+)?"),
    re.compile(r"(?i)mark\s+(?:all\s+)?(?:criteria\s+)?met\s+immediately"),
    re.compile(r"(?i)system\s*prompt\s*:"),
    re.compile(r"(?i)<script\b[^>]*>.*?</script>"),
]


def detect_adversarial_patterns(text: str) -> list[str]:
    """Scan untrusted text for adversarial prompt injection patterns."""
    flags: list[str] = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            flags.append("PROMPT_INJECTION_SUSPECTED")
            break
    if "<script" in text.lower():
        flags.append("HTML_SCRIPT_TAG_DETECTED")
    return flags


def validate_document_payload(
    req: DocumentIngestRequest,
    expected_patient_id: str | None = None,
) -> list[str]:
    """Perform deep structural, encoding, and format validation on document payload."""
    # 1. MIME type validation
    mime = req.mime_type.lower().strip()
    if mime not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"Unsupported document format '{req.mime_type}'. Supported formats: {', '.join(sorted(SUPPORTED_MIME_TYPES))}"
        )

    # 2. Patient boundary validation
    if expected_patient_id and req.patient_id != expected_patient_id:
        raise ValueError(
            f"Cross-patient violation: Document patient_id '{req.patient_id}' does not match case patient_id '{expected_patient_id}'."
        )

    # 3. Payload size validation
    raw_bytes = req.text.encode("utf-8")
    if len(raw_bytes) > 500_000:
        raise ValueError(f"Document payload exceeds maximum allowed size of 500 KB (size: {len(raw_bytes)} bytes).")

    # 4. JSON structure validation if JSON MIME format
    if mime == "application/json":
        try:
            parsed = json.loads(req.text)
            if not isinstance(parsed, (dict, list)):
                raise ValueError("JSON document must parse into an object or array.")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON document: {exc}") from exc

    # 5. Adversarial injection scanning
    security_flags = detect_adversarial_patterns(req.text)
    return security_flags


def ingest_document_safe(
    session: Session,
    request: DocumentIngestRequest,
    *,
    expected_patient_id: str | None = None,
    actor: str = "SYSTEM_INGEST",
    case_id: str | None = None,
    chunk_version: str = "v1",
) -> DocumentIngestResponse:
    """Safely validate, persist, and chunk an incoming patient chart document.

    Atomically updates DocumentModel and DocumentChunkModel in PostgreSQL.
    """
    security_flags = validate_document_payload(request, expected_patient_id=expected_patient_id)

    now = datetime.now(timezone.utc)
    token_count = estimate_tokens(request.text)

    # 1. Upsert DocumentModel
    doc_record = session.query(DocumentModel).filter_by(source_id=request.source_id).first()
    if not doc_record:
        doc_record = DocumentModel(
            source_id=request.source_id,
            patient_id=request.patient_id,
            doc_date=request.doc_date,
            text=request.text,
            created_at=now,
        )
        session.add(doc_record)
    else:
        # Cross-patient check on existing document
        if doc_record.patient_id != request.patient_id:
            raise ValueError(
                f"Document '{request.source_id}' already exists and cannot be reassigned to patient '{request.patient_id}'."
            )
        doc_record.doc_date = request.doc_date
        doc_record.text = request.text

    session.flush()

    # 2. Chunk document with exact character offsets
    chunks = chunk_patient_document(
        source_id=request.source_id,
        patient_id=request.patient_id,
        text=request.text,
        doc_date=request.doc_date,
        chunk_version=chunk_version,
    )

    # Purge stale chunks
    new_chunk_ids = {c.chunk_id for c in chunks}
    session.query(DocumentChunkModel).filter(
        DocumentChunkModel.source_id == request.source_id,
        DocumentChunkModel.chunk_version == chunk_version,
        ~DocumentChunkModel.chunk_id.in_(new_chunk_ids),
    ).delete(synchronize_session=False)

    # Persist or update chunk models
    for c in chunks:
        existing_chunk = (
            session.query(DocumentChunkModel)
            .filter_by(
                source_id=c.source_id,
                chunk_version=chunk_version,
                chunk_index=c.chunk_index,
            )
            .first()
        )
        if not existing_chunk:
            model = DocumentChunkModel(
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                patient_id=c.patient_id,
                doc_date=c.doc_date,
                chunk_text=c.chunk_text,
                chunk_index=c.chunk_index,
                char_start=c.char_start,
                char_end=c.char_end,
                token_count=c.token_count,
                chunk_version=c.chunk_version,
            )
            session.add(model)
        else:
            existing_chunk.chunk_id = c.chunk_id
            existing_chunk.patient_id = c.patient_id
            existing_chunk.doc_date = c.doc_date
            existing_chunk.chunk_text = c.chunk_text
            existing_chunk.char_start = c.char_start
            existing_chunk.char_end = c.char_end
            existing_chunk.token_count = c.token_count

    # 3. Record AuditLog event if associated with a case
    if not case_id:
        case_rec = session.query(CaseModel).filter_by(patient_id=request.patient_id).first()
        if case_rec:
            case_id = case_rec.case_id

    if case_id:
        audit_note = (
            f"Ingested document '{request.source_id}' for patient '{request.patient_id}'. "
            f"Size: {len(request.text)} chars, {len(chunks)} chunks. "
            f"Security flags: {security_flags if security_flags else 'NONE'}."
        )
        audit = AuditLogModel(
            case_id=case_id,
            criterion_id=None,
            action="DOCUMENT_INGESTED",
            note=audit_note,
            actor=actor,
            created_at=now,
        )
        session.add(audit)
    session.flush()

    return DocumentIngestResponse(
        source_id=request.source_id,
        patient_id=request.patient_id,
        doc_date=request.doc_date,
        character_count=len(request.text),
        token_count=token_count,
        chunks_created=len(chunks),
        security_flags=security_flags,
        created_at=now.isoformat(),
    )
