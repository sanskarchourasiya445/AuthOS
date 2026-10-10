"""AuthOS single source of truth Pydantic v2 schemas and domain models.

All schemas follow strict validation policies:
- Explicit types and closed enumerations.
- Extra fields forbidden (`extra="forbid"`).
- Leading and trailing whitespace stripped on strings.
- Deterministic verification rules enforced at model validation boundaries:
  * A MET criterion result MUST have verified=True and at least one evidence item.
  * A non-MET criterion result MUST have verified=False.
  * Absence of evidence cannot produce a positive status.
"""
from enum import Enum
from typing import Annotated, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CriterionStatus(str, Enum):
    """Evaluation status for a single policy criterion."""
    MET = "MET"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTED = "CONTRADICTED"


class CaseStatus(str, Enum):
    """Lifecycle state of an authorization review case."""
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    RESULTS_READY = "RESULTS_READY"
    IN_HUMAN_REVIEW = "IN_HUMAN_REVIEW"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ReviewActionType(str, Enum):
    """Explicit human reviewer action on a criterion."""
    REQUEST_INFORMATION = "request_information"
    ACCEPT_GAP = "accept_gap"
    FLAG_CONTRADICTION = "flag_contradiction"
    CUSTOM_NOTE = "custom_note"


class FinalizationActionType(str, Enum):
    """Explicit human action on final review packet."""
    APPROVE_PACKET = "approve_packet"
    REQUEST_EDITS = "request_edits"
    REJECT_PACKET = "reject_packet"


class ErrorCode(str, Enum):
    """Machine-readable API error codes."""
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    RUN_ALREADY_IN_PROGRESS = "RUN_ALREADY_IN_PROGRESS"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    PACKET_NOT_FINALIZED = "PACKET_NOT_FINALIZED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    INVALID_DOCUMENT_FORMAT = "INVALID_DOCUMENT_FORMAT"
    DOCUMENT_SIZE_EXCEEDED = "DOCUMENT_SIZE_EXCEEDED"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    CLAIM_ANALYSIS_FAILED = "CLAIM_ANALYSIS_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class SchemaBase(BaseModel):
    """Base model enforcing common configuration across all contracts."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        use_enum_values=False,
    )


class EvidencePolarity(str, Enum):
    """Polarity of a cited evidence passage relative to the criterion claim."""
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    UNCLEAR = "UNCLEAR"


class EvidenceItem(SchemaBase):
    """A traceable excerpt cited as supporting, ambiguous, or contradictory evidence."""
    source_id: Annotated[str, Field(min_length=1, description="Identifier of the source document in the patient chart")]
    patient_id: Annotated[str, Field(min_length=1, description="Identifier of the patient the source belongs to")]
    quote: Annotated[str, Field(min_length=1, description="Verbatim text quote from the source document")]
    document_date: Annotated[str | None, Field(default=None, description="ISO-formatted document date, if available")] = None
    retrieval_round: Annotated[int, Field(default=1, ge=1, le=5, description="Search round in which this evidence was retrieved")] = 1
    chunk_id: str | None = Field(default=None, description="Persisted chunk identifier, if applicable")
    char_start: int | None = Field(default=None, ge=0, description="Exact start character offset in raw document")
    char_end: int | None = Field(default=None, ge=0, description="Exact end character offset in raw document")
    polarity: EvidencePolarity = Field(default=EvidencePolarity.SUPPORTING, description="Evidence polarity relative to the claim")


class RetryLogEntry(SchemaBase):
    """Audit log entry for a bounded corrective retrieval attempt."""
    round: Annotated[int, Field(ge=1, le=5, description="Retrieval attempt index")]
    query: Annotated[str, Field(min_length=1, description="Generated search query targeting missing facts")]
    found: list[str] = Field(default_factory=list, description="Clinical facts identified in this round")
    missing: list[str] = Field(default_factory=list, description="Clinical facts still missing after this round")
    sufficient: bool = Field(description="Whether the retrieved evidence satisfies the required facts")


class Criterion(SchemaBase):
    """A single medical necessity requirement extracted from a payer policy."""
    id: Annotated[str, Field(min_length=1, description="Criterion identifier (e.g. C1, C2)")]
    text: Annotated[str, Field(min_length=1, description="Criterion policy statement")]
    evidence_type: str | None = Field(default=None, description="Type of clinical evidence required")
    min_duration_days: int | None = Field(default=None, ge=0, description="Minimum duration required in days, if applicable")
    required_facts: list[str] = Field(default_factory=list, description="Required clinical facts to substantiate this criterion")
    exception_ids: list[str] = Field(default_factory=list, description="Policy exception IDs that may waive this criterion")
    source_chunk: str | None = Field(default=None, description="Policy chunk from which criterion was extracted")


class CriterionResult(SchemaBase):
    """Evaluation output for a single criterion with provenance and retry history."""
    criterion_id: Annotated[str, Field(min_length=1, description="Referenced criterion ID")]
    status: CriterionStatus = Field(description="Evidence status: MET, MISSING, AMBIGUOUS, or CONTRADICTED")
    verified: bool = Field(default=False, description="Whether evidence provenance and exact quote have been deterministically verified")
    evidence: list[EvidenceItem] = Field(default_factory=list, description="Cited evidence items from the patient chart")
    missing_facts: list[str] = Field(default_factory=list, description="Clinical facts that remain missing")
    retry_log: list[RetryLogEntry] = Field(default_factory=list, description="History of retrieval and sufficiency evaluation rounds")
    validator_flags: list[str] = Field(default_factory=list, description="Diagnostic flags raised by deterministic validators")
    reason: str | None = Field(default=None, description="Human-readable explanation of status and evidence disposition")
    criterion_text: str | None = Field(default=None, description="Policy text of the evaluated criterion")
    verification_version: str = Field(default="deterministic-v1", description="Version of the verification engine applied")
    conflicting_evidence: list[EvidenceItem] = Field(default_factory=list, description="Evidence items that conflict with the claim")
    review_required: bool = Field(default=True, description="Whether human reviewer adjudication is required")

    @model_validator(mode="after")
    def validate_status_and_verification_rules(self) -> "CriterionResult":
        """Enforce non-negotiable safety rules between status, verification, and evidence."""
        if self.status == CriterionStatus.MET:
            if not self.verified:
                raise ValueError("A MET criterion result must have verified=True")
            if not self.evidence:
                raise ValueError("A MET criterion result must have at least one supporting evidence item")
            if any(e.polarity != EvidencePolarity.SUPPORTING for e in self.evidence):
                raise ValueError("A MET criterion result cannot cite non-supporting evidence")
            if self.missing_facts:
                raise ValueError("A MET criterion result cannot have missing_facts")
            if self.conflicting_evidence:
                raise ValueError("A MET criterion result cannot have unresolved conflicting_evidence")
        else:
            if self.verified:
                raise ValueError("A non-MET criterion result must have verified=False")
            if not self.review_required:
                raise ValueError("Every non-MET criterion result must require human review (review_required=True)")
        return self


class ReviewActionRequest(SchemaBase):
    """Reviewer annotation or gap disposition on a specific criterion."""
    criterion_id: Annotated[str, Field(min_length=1, description="Target criterion ID")]
    action: ReviewActionType = Field(description="Reviewer action type")
    note: Annotated[str, Field(min_length=1, description="Reviewer rationale or instruction")]


class ReviewActionResponse(SchemaBase):
    """Audit confirmation of a recorded reviewer action."""
    case_id: str
    criterion_id: str
    action: ReviewActionType
    note: str
    recorded_at: str


class FinalizationActionRequest(SchemaBase):
    """Human decision to approve, request edits on, or reject a packet."""
    action: FinalizationActionType = Field(description="Approval or disposition action")
    reviewer_note: Annotated[str, Field(min_length=1, description="Justification for finalization decision")]


class PacketCriterionRow(SchemaBase):
    """Structured criterion row in the rendered review packet."""
    criterion_id: str
    criterion: str
    status: CriterionStatus
    evidence: list[EvidenceItem] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    validator_flags: list[str] = Field(default_factory=list)
    verification_version: str = "deterministic-v1"
    reason: str = ""
    review_required: bool = True


class ReviewPacket(SchemaBase):
    """Auditable review packet prepared for human review and finalization."""
    case_id: str
    patient_id: str
    policy_id: str | None = None
    packet_type: str = "SYNTHETIC_DEMO_REVIEW_PACKET"
    decision_authority: str = "HUMAN_REVIEWER"
    criteria: list[PacketCriterionRow] = Field(default_factory=list)
    disclaimer: str = "Preparation aid only. Not a medical-necessity or coverage decision."
    finalized: bool = False
    finalized_at: str | None = None
    reviewer_note: str | None = None
    generated_at: str | None = None
    audit_events: list[dict[str, Any]] = Field(default_factory=list)


class Case(SchemaBase):
    """Synthetic prior authorization case summary."""
    case_id: str
    patient_id: str
    service: str
    policy_id: str
    status: CaseStatus
    scenario: str
    created_at: str


class CaseResultsResponse(SchemaBase):
    """Detailed criteria results payload returned by GET /api/v1/cases/{case_id}/results."""
    case_id: str
    patient_id: str
    service: str
    policy_id: str
    status: CaseStatus
    scenario: str
    criteria_results: list[CriterionResult]


class ErrorDetail(SchemaBase):
    """RFC 7807 inspired structured error detail."""
    code: ErrorCode
    message: str
    request_id: str | None = None


class ErrorEnvelope(SchemaBase):
    """Standardized API error envelope."""
    error: ErrorDetail


class DocumentIngestRequest(SchemaBase):
    """Payload for ingesting a synthetic patient chart document."""
    source_id: Annotated[str, Field(min_length=1, max_length=64, description="Unique document source identifier")]
    patient_id: Annotated[str, Field(min_length=1, max_length=64, description="Owning synthetic patient identifier")]
    text: Annotated[str, Field(min_length=1, max_length=500_000, description="Verbatim raw document text")]
    doc_date: Annotated[str | None, Field(default=None, description="ISO-formatted document date (YYYY-MM-DD)")] = None
    mime_type: Annotated[str, Field(default="text/plain", description="MIME format: text/plain, text/markdown, application/json")] = "text/plain"


class DocumentIngestResponse(SchemaBase):
    """Confirmation output following validated document ingestion and chunking."""
    source_id: str
    patient_id: str
    doc_date: str | None
    character_count: int
    token_count: int
    chunks_created: int
    security_flags: list[str] = Field(default_factory=list, description="Security/adversarial detection flags")
    created_at: str


class AIClaimProposal(SchemaBase):
    """Advisory, non-authoritative AI claim proposal for a single policy criterion."""
    criterion_id: Annotated[str, Field(min_length=1, description="Policy criterion being evaluated")]
    proposed_status: CriterionStatus = Field(description="Advisory proposed status: MET, MISSING, AMBIGUOUS, CONTRADICTED")
    confidence: Annotated[float, Field(ge=0.0, le=1.0, description="Model uncertainty/confidence metric")]
    evidence_quotes: list[EvidenceItem] = Field(default_factory=list, description="Cited verbatim evidence quotes")
    missing_facts: list[str] = Field(default_factory=list, description="Clinical facts identified as missing")
    detected_gaps: list[str] = Field(default_factory=list, description="Potential documentation gaps identified")
    uncertainty_rationale: Annotated[str, Field(min_length=1, description="Structured explanation of uncertainty and evidence limits")]
    is_ai_generated: bool = Field(default=True, description="Strict marker distinguishing AI proposal from authoritative result")
    flags: list[str] = Field(default_factory=list, description="Diagnostic, safety, or prompt-injection audit flags")


class ClaimAnalysisResponse(SchemaBase):
    """Aggregated advisory claim analysis response for a prior-auth case."""
    case_id: str
    patient_id: str
    policy_id: str
    analyzer_provider: str
    proposals: list[AIClaimProposal]
    disclaimer: str = "AI-assisted claim analysis is advisory only. Not authoritative. Every evidence citation requires deterministic verification and human review."
    generated_at: str


class PatientDocumentSummary(SchemaBase):
    """Summary of a patient chart document for case navigation."""
    source_id: str
    patient_id: str
    doc_date: str | None = None
    character_count: int
    chunks_count: int = 0
    created_at: str


class PatientDocumentDetail(SchemaBase):
    """Detailed patient chart document with raw verbatim text and chunk boundaries."""
    source_id: str
    patient_id: str
    doc_date: str | None = None
    text: str
    character_count: int
    chunks_count: int = 0
    created_at: str

