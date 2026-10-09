"""Deterministic lexical retrieval baseline for AuthOS evidence candidates.

Guarantees:
- Strict patient isolation: clinical chart candidates are filtered by patient_id at the DB layer.
- Policy text and patient charts are retrieved independently in separate candidate sets.
- BM25Okapi scoring with deterministic tie-breaking.
- Exact source offsets and verbatim text preserved from persisted chunks.
- Zero vector embeddings, pgvector, LLMs, or autonomous agents in this baseline.
- Lexical relevance does NOT imply clinical support or verify a criterion.
"""
import math
import re
from collections import Counter
from sqlalchemy.orm import Session

from backend.db.models import DocumentChunkModel, PolicyChunkModel
from backend.rag.schemas import (
    EvidenceCandidate,
    PolicyCandidate,
    RetrievalResult,
)

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me",
    "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these",
    "they", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "we", "were", "what", "when", "where", "which", "while", "who",
    "whom", "why", "with", "would", "you", "your", "yours", "yourself",
}


def tokenize(text: str) -> list[str]:
    """Deterministic tokenization and stop-word filtering."""
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z0-9_\-]+\b", text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]


class BM25Okapi:
    """Lightweight, deterministic BM25Okapi scoring implementation."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.doc_lens = [len(doc) for doc in corpus]
        self.avgdl = (sum(self.doc_lens) / self.corpus_size) if self.corpus_size > 0 else 0.0
        self.doc_freqs: list[Counter] = [Counter(doc) for doc in corpus]

        # Calculate document frequency for each term in corpus
        df: dict[str, int] = {}
        for freq in self.doc_freqs:
            for term in freq:
                df[term] = df.get(term, 0) + 1
        self.df = df

        # Precompute IDF for all observed terms
        self.idf: dict[str, float] = {}
        for term, freq in self.df.items():
            # Standard Lucene/BM25Okapi IDF formulation with +1 to guarantee non-negative weights
            self.idf[term] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def score_document(self, doc_idx: int, query_tokens: list[str]) -> tuple[float, list[str]]:
        """Score a specific document in corpus against query tokens."""
        if self.corpus_size == 0 or not query_tokens:
            return 0.0, []

        doc_len = self.doc_lens[doc_idx]
        if doc_len == 0:
            return 0.0, []

        doc_freq = self.doc_freqs[doc_idx]
        total_score = 0.0
        matched: list[str] = []

        len_norm = 1.0 if self.avgdl == 0.0 else (1.0 - self.b + self.b * (doc_len / self.avgdl))

        for term in query_tokens:
            tf = doc_freq.get(term, 0)
            if tf > 0:
                idf = self.idf.get(term, 0.0)
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * len_norm
                total_score += idf * (numerator / denominator)
                matched.append(term)

        return total_score, matched


def retrieve_chart_candidates(
    session: Session,
    *,
    patient_id: str,
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
    chunk_version: str = "v1",
) -> list[EvidenceCandidate]:
    """Retrieve ranked patient chart evidence candidates for a specific patient.

    Enforces strict patient boundary isolation. Chunks belonging to any other
    patient are never retrieved or evaluated.
    """
    if not patient_id or not query or not query.strip():
        return []

    # 1. Query persisted chunks strictly isolated by patient_id
    chunks = (
        session.query(DocumentChunkModel)
        .filter(
            DocumentChunkModel.patient_id == patient_id,
            DocumentChunkModel.chunk_version == chunk_version,
        )
        .order_by(DocumentChunkModel.source_id, DocumentChunkModel.chunk_index)
        .all()
    )

    if not chunks:
        return []

    # Defensive check: ensure zero patient ID contamination
    for chunk in chunks:
        if chunk.patient_id != patient_id:
            raise ValueError(f"Cross-patient violation: chunk {chunk.chunk_id} does not match {patient_id}")

    # 2. Tokenize corpus and query
    corpus = [tokenize(c.chunk_text) for c in chunks]
    query_tokens = tokenize(query)

    if not query_tokens:
        return []

    bm25 = BM25Okapi(corpus)

    # 3. Score candidates
    scored_candidates = []
    for idx, chunk in enumerate(chunks):
        score, matched = bm25.score_document(idx, query_tokens)
        if score > min_score and matched:
            scored_candidates.append({
                "chunk": chunk,
                "score": score,
                "matched": matched,
            })

    # 4. Deterministic tie-breaking:
    # Sort order: (-score, doc_date_ascending, source_id, chunk_index, chunk_id)
    def tie_break_key(item):
        c = item["chunk"]
        date_val = c.doc_date or ""
        return (-round(item["score"], 6), date_val, c.source_id, c.chunk_index, c.chunk_id)

    scored_candidates.sort(key=tie_break_key)

    # 5. Format top-k candidates
    candidates: list[EvidenceCandidate] = []
    for rank, item in enumerate(scored_candidates[:top_k], start=1):
        c = item["chunk"]
        candidates.append(
            EvidenceCandidate(
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                patient_id=c.patient_id,
                doc_date=c.doc_date,
                chunk_text=c.chunk_text,
                char_start=c.char_start,
                char_end=c.char_end,
                score=round(item["score"], 4),
                rank=rank,
                matched_terms=item["matched"],
                token_count=c.token_count,
            )
        )

    return candidates


def retrieve_policy_candidates(
    session: Session,
    *,
    policy_id: str,
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
    chunk_version: str = "v1",
) -> list[PolicyCandidate]:
    """Retrieve ranked policy text sections for a specific policy.

    Policy text is stored and queried completely separately from patient records.
    """
    if not policy_id or not query or not query.strip():
        return []

    chunks = (
        session.query(PolicyChunkModel)
        .filter(
            PolicyChunkModel.policy_id == policy_id,
            PolicyChunkModel.chunk_version == chunk_version,
        )
        .order_by(PolicyChunkModel.chunk_index)
        .all()
    )

    if not chunks:
        return []

    corpus = [tokenize(c.chunk_text) for c in chunks]
    query_tokens = tokenize(query)

    if not query_tokens:
        return []

    bm25 = BM25Okapi(corpus)

    scored_candidates = []
    for idx, chunk in enumerate(chunks):
        score, matched = bm25.score_document(idx, query_tokens)
        if score > min_score and matched:
            scored_candidates.append({
                "chunk": chunk,
                "score": score,
                "matched": matched,
            })

    def tie_break_key(item):
        c = item["chunk"]
        return (-round(item["score"], 6), c.chunk_index, c.chunk_id)

    scored_candidates.sort(key=tie_break_key)

    candidates: list[PolicyCandidate] = []
    for rank, item in enumerate(scored_candidates[:top_k], start=1):
        c = item["chunk"]
        candidates.append(
            PolicyCandidate(
                chunk_id=c.chunk_id,
                policy_id=c.policy_id,
                section_id=c.section_id,
                heading=c.heading,
                chunk_text=c.chunk_text,
                char_start=c.char_start,
                char_end=c.char_end,
                score=round(item["score"], 4),
                rank=rank,
                matched_terms=item["matched"],
                token_count=c.token_count,
            )
        )

    return candidates


def retrieve_evidence_candidates(
    session: Session,
    *,
    patient_id: str,
    query: str,
    policy_id: str | None = None,
    top_k: int = 5,
    min_score: float = 0.0,
    chunk_version: str = "v1",
) -> RetrievalResult:
    """Unified entry point for retrieving evidence candidates for a patient and policy query.

    Explicitly keeps patient chart evidence candidates and policy section candidates
    in separate fields. Never conflates patient data with policy requirements.
    """
    chart_candidates = retrieve_chart_candidates(
        session,
        patient_id=patient_id,
        query=query,
        top_k=top_k,
        min_score=min_score,
        chunk_version=chunk_version,
    )

    policy_candidates: list[PolicyCandidate] = []
    if policy_id:
        policy_candidates = retrieve_policy_candidates(
            session,
            policy_id=policy_id,
            query=query,
            top_k=top_k,
            min_score=min_score,
            chunk_version=chunk_version,
        )

    return RetrievalResult(
        query=query,
        patient_id=patient_id,
        policy_id=policy_id,
        chart_candidates=chart_candidates,
        policy_candidates=policy_candidates,
        total_candidates=len(chart_candidates) + len(policy_candidates),
    )
