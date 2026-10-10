"""SQLAlchemy declarative models for AuthOS relational persistence."""
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PolicyModel(Base):
    """Payer policy header record."""
    __tablename__ = "policies"

    policy_id = Column(String(64), primary_key=True)
    service = Column(String(128), nullable=False)
    version = Column(String(32), nullable=False)
    notice = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    criteria = relationship("PolicyCriterionModel", back_populates="policy", cascade="all, delete-orphan", passive_deletes=True)
    cases = relationship("CaseModel", back_populates="policy")
    chunks = relationship("PolicyChunkModel", back_populates="policy", cascade="all, delete-orphan", passive_deletes=True)


class PolicyCriterionModel(Base):
    """Individual clinical criterion extracted from a payer policy."""
    __tablename__ = "policy_criteria"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(String(64), ForeignKey("policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    criterion_id = Column(String(32), nullable=False)
    text = Column(Text, nullable=False)
    evidence_expectation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("policy_id", "criterion_id", name="uq_policy_criterion"),
    )

    policy = relationship("PolicyModel", back_populates="criteria")


class DocumentModel(Base):
    """Synthetic patient chart source records."""
    __tablename__ = "documents"

    source_id = Column(String(64), primary_key=True)
    patient_id = Column(String(64), nullable=False, index=True)
    doc_date = Column(String(32), nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    chunks = relationship("DocumentChunkModel", back_populates="document", cascade="all, delete-orphan", passive_deletes=True)


class CaseModel(Base):
    """Prior authorization review case."""
    __tablename__ = "cases"

    case_id = Column(String(64), primary_key=True)
    patient_id = Column(String(64), nullable=False, index=True)
    service = Column(String(128), nullable=False)
    policy_id = Column(String(64), ForeignKey("policies.policy_id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="RESULTS_READY")
    scenario = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_note = Column(Text, nullable=True)

    policy = relationship("PolicyModel", back_populates="cases")
    criterion_results = relationship("CriterionResultModel", back_populates="case", cascade="all, delete-orphan")
    audit_entries = relationship("AuditLogModel", back_populates="case", cascade="all, delete-orphan")
    agent_proposals = relationship("AgentProposalModel", back_populates="case", cascade="all, delete-orphan")


class CriterionResultModel(Base):
    """Evaluation output and retry log for a single case criterion."""
    __tablename__ = "criterion_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    criterion_id = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    verified = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=False, default=list)
    conflicting_evidence = Column(JSON, nullable=False, default=list)
    missing_facts = Column(JSON, nullable=False, default=list)
    retry_log = Column(JSON, nullable=False, default=list)
    validator_flags = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("case_id", "criterion_id", name="uq_case_criterion"),
    )

    case = relationship("CaseModel", back_populates="criterion_results")


class AuditLogModel(Base):
    """Append-only audit trail for reviewer annotations and packet actions."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    criterion_id = Column(String(32), nullable=True)
    action = Column(String(64), nullable=False)
    note = Column(Text, nullable=False)
    actor = Column(String(128), nullable=False, default="HUMAN_REVIEWER (UNAUTHENTICATED_DEV)")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    case = relationship("CaseModel", back_populates="audit_entries")


class PolicyChunkModel(Base):
    """Deterministic section-level chunks of payer policies."""
    __tablename__ = "policy_chunks"

    chunk_id = Column(String(128), primary_key=True)
    policy_id = Column(String(64), ForeignKey("policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(String(64), nullable=True)
    heading = Column(String(256), nullable=True)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=False)
    chunk_version = Column(String(32), nullable=False, default="v1")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("policy_id", "chunk_version", "chunk_index", name="uq_policy_chunk_pos"),
    )

    policy = relationship("PolicyModel", back_populates="chunks")


class DocumentChunkModel(Base):
    """Deterministic paragraph-level chunks of patient chart documents."""
    __tablename__ = "document_chunks"

    chunk_id = Column(String(128), primary_key=True)
    source_id = Column(String(64), ForeignKey("documents.source_id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id = Column(String(64), nullable=False, index=True)
    doc_date = Column(String(32), nullable=True)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=False)
    chunk_version = Column(String(32), nullable=False, default="v1")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_id", "chunk_version", "chunk_index", name="uq_document_chunk_pos"),
    )

    document = relationship("DocumentModel", back_populates="chunks")


class AgentProposalModel(Base):
    """Persisted advisory proposal from the multi-agent workflow, strictly separated from authoritative records."""
    __tablename__ = "agent_proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    criterion_id = Column(String(32), nullable=False)
    proposed_status = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    uncertainty_rationale = Column(Text, nullable=False)
    evidence_quotes = Column(JSON, nullable=False, default=list)
    missing_facts = Column(JSON, nullable=False, default=list)
    detected_gaps = Column(JSON, nullable=False, default=list)
    retrieval_rounds = Column(Integer, nullable=False, default=1)
    is_verified = Column(Boolean, nullable=False, default=False)
    verification_feedback = Column(JSON, nullable=True)
    flags = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("case_id", "run_id", "criterion_id", name="uq_case_run_criterion"),
    )

    case = relationship("CaseModel", back_populates="agent_proposals")


