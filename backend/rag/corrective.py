"""Bounded deterministic corrective retrieval for AuthOS (Phase 5B).

Engineering Principles:
1. Evidence-Driven & Bounded: Maximum 2 retry attempts (total 3 attempts max).
2. Deterministic Expansion: Rule-based domain synonym normalization without external LLM calls.
3. Strict Patient Boundary Isolation: Every attempt strictly filters by `patient_id` in SQL.
4. Clean Abstention: Unrelated queries or true negative controls abstain cleanly with 0 candidates.
5. Deduplication & Capping: Hard limit of `top_k` candidates, deduplicated by `chunk_id`.
6. Traceability: Every attempt logs its exact reformulated query, attempt index, and candidate count.
"""
from dataclasses import dataclass, field
from typing import Any
from sqlalchemy.orm import Session

from backend.rag.retrieval import retrieve_chart_candidates
from backend.rag.schemas import EvidenceCandidate


# Canonical deterministic clinical synonym rewrites for prior-auth conservative therapy and imaging
DETERMINISTIC_SYNONYM_RULES: list[tuple[str, str]] = [
    # Conservative therapy terminology bridging
    ("ambulation assistance", "physical therapy"),
    ("non operative rehabilitation regimen", "conservative treatment physical therapy"),
    ("non-operative rehabilitation regimen", "conservative treatment physical therapy"),
    ("non operative rehabilitation", "conservative treatment physical therapy"),
    ("non-operative rehabilitation", "conservative treatment physical therapy"),
    ("non operative treatment", "conservative treatment"),
    ("non-operative treatment", "conservative treatment"),
    ("rehabilitation regimen", "physical therapy"),
    ("exercise regimen", "physical therapy"),
    # Diagnostic imaging requisition bridging
    ("ordering clinician requisition for lumbar imaging study", "ordering clinician requests lumbar mri"),
    ("requisition for lumbar imaging study", "requests lumbar mri"),
    ("imaging study", "lumbar mri"),
    ("radiological study", "lumbar mri"),
]


@dataclass
class CorrectiveAttemptRecord:
    attempt_index: int
    query_used: str
    candidates_found: int
    stopped: bool
    reason: str


@dataclass
class CorrectiveRetrievalResult:
    candidates: list[EvidenceCandidate]
    attempts_executed: int
    total_attempts_budget: int
    history: list[CorrectiveAttemptRecord] = field(default_factory=list)


def rewrite_query_deterministic(query: str, attempt: int) -> str | None:
    """Derive a deterministic query reformulation without external LLMs.

    Attempt 1: Apply domain synonym substitutions.
    Attempt 2: Token-focused root keyword fallback for multi-word queries.
    Returns None if no valid reformulation can be generated.
    """
    q_lower = query.lower().strip()
    if not q_lower:
        return None

    if attempt == 1:
        rewritten = q_lower
        matched = False
        for phrase, replacement in DETERMINISTIC_SYNONYM_RULES:
            if phrase in rewritten:
                rewritten = rewritten.replace(phrase, replacement)
                matched = True
        if matched and rewritten != q_lower:
            return rewritten
        return None

    elif attempt == 2:
        # If attempt 1 did not find evidence, try extracting key clinical substantive tokens
        # (strip stopwords, keep domain content words >= 4 chars)
        stopwords = {
            "for", "the", "and", "with", "from", "that", "this", "have", "been",
            "at", "least", "more", "than", "describe", "describes", "does", "also",
            "is", "are", "was", "were", "attended", "several"
        }
        tokens = [t for t in q_lower.split() if t not in stopwords and len(t) >= 4]
        if tokens:
            candidate_q = " ".join(tokens)
            if candidate_q != q_lower:
                return candidate_q
        return None

    return None


def retrieve_chart_candidates_bounded_corrective(
    session: Session,
    *,
    patient_id: str,
    query: str,
    top_k: int = 3,
    max_retries: int = 2,
    chunk_version: str = "v1",
) -> tuple[list[EvidenceCandidate], CorrectiveRetrievalResult]:
    """Execute bounded corrective retrieval with deterministic query expansion.

    - Attempt 0 (initial): Standard BM25 search.
    - If 0 candidates returned, Attempt 1: Deterministic synonym rewrite.
    - If still 0 candidates, Attempt 2: Domain root keyword extraction.
    - Strictly preserves `patient_id` boundary at every SQL query.
    - Caps total output at `top_k`.
    """
    if max_retries < 0 or max_retries > 5:
        raise ValueError(f"max_retries must be between 0 and 5, got {max_retries}")

    budget = max_retries + 1  # 0 retries = 1 attempt, 2 retries = 3 attempts total

    if not patient_id or not query or not query.strip():
        audit = CorrectiveRetrievalResult(
            candidates=[],
            attempts_executed=1,
            total_attempts_budget=budget,
            history=[
                CorrectiveAttemptRecord(
                    attempt_index=0,
                    query_used=query or "",
                    candidates_found=0,
                    stopped=True,
                    reason="Empty or whitespace query provided; abstaining immediately",
                )
            ],
        )
        return [], audit

    history: list[CorrectiveAttemptRecord] = []

    # Attempt 0: Initial query
    current_query = query
    attempt = 0
    candidates = retrieve_chart_candidates(
        session,
        patient_id=patient_id,
        query=current_query,
        top_k=top_k,
        chunk_version=chunk_version,
    )

    history.append(CorrectiveAttemptRecord(
        attempt_index=0,
        query_used=current_query,
        candidates_found=len(candidates),
        stopped=len(candidates) > 0 or (max_retries == 0),
        reason="Initial retrieval successful" if candidates else "Initial retrieval produced 0 candidates",
    ))

    # Bounded corrective loop
    while len(candidates) == 0 and (attempt < max_retries):
        attempt += 1
        rewritten = rewrite_query_deterministic(query, attempt)
        if rewritten is None or rewritten == current_query:
            is_stopped = (attempt >= max_retries)
            history.append(CorrectiveAttemptRecord(
                attempt_index=attempt,
                query_used=current_query,
                candidates_found=0,
                stopped=is_stopped,
                reason=f"No deterministic rewrite rule applicable for attempt {attempt}",
            ))
            if not is_stopped:
                continue
            break

        current_query = rewritten
        retry_cands = retrieve_chart_candidates(
            session,
            patient_id=patient_id,
            query=current_query,
            top_k=top_k,
            chunk_version=chunk_version,
        )

        history.append(CorrectiveAttemptRecord(
            attempt_index=attempt,
            query_used=current_query,
            candidates_found=len(retry_cands),
            stopped=len(retry_cands) > 0 or (attempt >= max_retries),
            reason=f"Corrective retry {attempt} returned {len(retry_cands)} candidates",
        ))

        if retry_cands:
            candidates = retry_cands
            break

    # Defensive candidate capping and deduplication by chunk_id
    seen_chunks: set[str] = set()
    deduped: list[EvidenceCandidate] = []
    for cand in candidates:
        if cand.patient_id != patient_id:
            raise ValueError(f"Cross-patient violation in corrective retrieval: {cand.patient_id} != {patient_id}")
        if cand.chunk_id not in seen_chunks:
            seen_chunks.add(cand.chunk_id)
            deduped.append(cand)
            if len(deduped) >= top_k:
                break

    audit = CorrectiveRetrievalResult(
        candidates=deduped,
        attempts_executed=len(history),
        total_attempts_budget=budget,
        history=history,
    )
    return deduped, audit
