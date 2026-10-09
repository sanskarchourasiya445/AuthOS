"""Typed schemas for deterministic document ingestion and chunking."""
from pydantic import BaseModel, ConfigDict, Field


class IngestionBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PolicySection(IngestionBase):
    """Parsed section of a payer policy document."""
    section_id: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PolicyChunk(IngestionBase):
    """Deterministic section-level chunk from a payer policy."""
    chunk_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    section_id: str | None = None
    heading: str | None = None
    chunk_text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    token_count: int = Field(ge=0)
    chunk_version: str = "v1"


class DocumentChunk(IngestionBase):
    """Deterministic paragraph-level chunk from a patient chart document."""
    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    doc_date: str | None = None
    chunk_text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    token_count: int = Field(ge=0)
    chunk_version: str = "v1"


class EvidenceCandidate(IngestionBase):
    """Ranked evidence candidate passage retrieved from patient chart."""
    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    doc_date: str | None = None
    chunk_text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    score: float = Field(ge=0.0)
    rank: int = Field(ge=1)
    matched_terms: list[str] = Field(default_factory=list)
    token_count: int = Field(ge=0)
    retrieval_method: str = "bm25"


class PolicyCandidate(IngestionBase):
    """Ranked policy section passage retrieved from payer policy."""
    chunk_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    section_id: str | None = None
    heading: str | None = None
    chunk_text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    score: float = Field(ge=0.0)
    rank: int = Field(ge=1)
    matched_terms: list[str] = Field(default_factory=list)
    token_count: int = Field(ge=0)
    retrieval_method: str = "bm25"


class RetrievalResult(IngestionBase):
    """Deterministic retrieval response containing isolated chart and policy candidates."""
    query: str
    patient_id: str | None = None
    policy_id: str | None = None
    chart_candidates: list[EvidenceCandidate] = Field(default_factory=list)
    policy_candidates: list[PolicyCandidate] = Field(default_factory=list)
    total_candidates: int = 0
