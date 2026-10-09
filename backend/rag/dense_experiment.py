"""Controlled dense and hybrid retrieval experiment for AuthOS.

EXPERIMENTAL NOTICE:
This module is a strictly controlled comparative evaluation harness designed to compare:
1. Pure Lexical Baseline (BM25Okapi)
2. Dense Embedding Retrieval (BAAI/bge-small-en-v1.5 via local ONNX runtime)
3. Hybrid Retrieval via Reciprocal Rank Fusion (RRF)

Guarantees & Constraints:
- 100% local CPU execution via ONNX runtime (no external network/cloud calls during inference).
- Strict patient-boundary isolation enforced before embedding/scoring.
- Verifiable character offsets and exact text preserved.
- No pgvector required; in-memory vector similarity over isolated patient chunks.
- Retrieval relevance != criterion verification.
"""
from dataclasses import dataclass, field
import numpy as np
from sqlalchemy.orm import Session
from fastembed import TextEmbedding

from backend.db.models import DocumentChunkModel
from backend.rag.retrieval import retrieve_chart_candidates
from backend.rag.schemas import EvidenceCandidate

MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Cached local embedding model instance
_EMBED_MODEL: TextEmbedding | None = None


def get_embedding_model() -> TextEmbedding:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        _EMBED_MODEL = TextEmbedding(model_name=MODEL_NAME)
    return _EMBED_MODEL


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two 1D vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def retrieve_dense_chart_candidates(
    session: Session,
    *,
    patient_id: str,
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
    chunk_version: str = "v1",
) -> list[EvidenceCandidate]:
    """Retrieve ranked clinical chart evidence candidates using local dense embeddings.

    Enforces strict patient boundary isolation. Chunks belonging to any other
    patient are never retrieved or embedded.
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

    # Defensive check: zero patient ID contamination
    for chunk in chunks:
        if chunk.patient_id != patient_id:
            raise ValueError(f"Cross-patient violation: chunk {chunk.chunk_id} does not match {patient_id}")

    model = get_embedding_model()

    # 2. Embed query and document texts locally
    chunk_texts = [c.chunk_text for c in chunks]
    doc_embeddings = list(model.embed(chunk_texts))
    query_embedding = list(model.embed([query]))[0]

    # 3. Compute cosine similarity
    scored_candidates = []
    for idx, chunk in enumerate(chunks):
        score = cosine_similarity(query_embedding, doc_embeddings[idx])
        if score > min_score:
            scored_candidates.append({
                "chunk": chunk,
                "score": score,
            })

    # 4. Deterministic tie-breaking:
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
                matched_terms=[],
                token_count=c.token_count,
                retrieval_method="dense",
            )
        )

    return candidates


def retrieve_hybrid_chart_candidates(
    session: Session,
    *,
    patient_id: str,
    query: str,
    top_k: int = 5,
    rrf_k: int = 60,
    chunk_version: str = "v1",
) -> list[EvidenceCandidate]:
    """Retrieve ranked candidates via Reciprocal Rank Fusion (RRF) of BM25 and Dense retrieval.

    RRF combines rankings without scale distortion:
    RRF_Score(d) = sum(1 / (rrf_k + rank_m(d))) for m in {bm25, dense}
    """
    if not patient_id or not query or not query.strip():
        return []

    # Get larger pools for fusion
    bm25_cands = retrieve_chart_candidates(
        session, patient_id=patient_id, query=query, top_k=top_k * 2, chunk_version=chunk_version
    )
    dense_cands = retrieve_dense_chart_candidates(
        session, patient_id=patient_id, query=query, top_k=top_k * 2, chunk_version=chunk_version
    )

    rrf_scores: dict[str, float] = {}
    candidate_map: dict[str, EvidenceCandidate] = {}

    for c in bm25_cands:
        candidate_map[c.chunk_id] = c
        rrf_scores[c.chunk_id] = rrf_scores.get(c.chunk_id, 0.0) + (1.0 / (rrf_k + c.rank))

    for c in dense_cands:
        candidate_map[c.chunk_id] = c
        rrf_scores[c.chunk_id] = rrf_scores.get(c.chunk_id, 0.0) + (1.0 / (rrf_k + c.rank))

    scored_items = []
    for chunk_id, score in rrf_scores.items():
        base_cand = candidate_map[chunk_id]
        scored_items.append({
            "cand": base_cand,
            "rrf_score": score,
        })

    def tie_break_key(item):
        c = item["cand"]
        date_val = c.doc_date or ""
        return (-round(item["rrf_score"], 6), date_val, c.source_id, c.chunk_id)

    scored_items.sort(key=tie_break_key)

    candidates: list[EvidenceCandidate] = []
    for rank, item in enumerate(scored_items[:top_k], start=1):
        c = item["cand"]
        candidates.append(
            EvidenceCandidate(
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                patient_id=c.patient_id,
                doc_date=c.doc_date,
                chunk_text=c.chunk_text,
                char_start=c.char_start,
                char_end=c.char_end,
                score=round(item["rrf_score"], 6),
                rank=rank,
                matched_terms=c.matched_terms,
                token_count=c.token_count,
                retrieval_method="hybrid_rrf",
            )
        )

    return candidates


# --- Comparative Evaluation Harness ---

@dataclass
class ComparativeCase:
    case_id: str
    patient_id: str
    query: str
    expected_source_ids: list[str]
    prohibited_patient_ids: list[str]
    category: str
    description: str


# Unified 10 benchmark test cases
COMPARATIVE_BENCHMARK_CASES: list[ComparativeCase] = [
    # Positive Ground Truth (Quality Benchmark)
    ComparativeCase(
        case_id="EXP-01-RELEVANT",
        patient_id="SYN-P001",
        query="Conservative treatment history is documented for at least six weeks physical therapy",
        expected_source_ids=["SYN-P001-PT-02"],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="relevant",
        description="Expected relevant physical therapy note for C2.",
    ),
    ComparativeCase(
        case_id="EXP-02-IRRELEVANT-KEYWORD",
        patient_id="SYN-P001",
        query="low back pain persistent symptoms duration",
        expected_source_ids=["SYN-P001-NOTE-01"],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="irrelevant_match",
        description="Clinical examination note vs radiology order keyword overlap.",
    ),
    ComparativeCase(
        case_id="EXP-03-CONTRADICTORY",
        patient_id="SYN-P003",
        query="physical therapy offered conservative treatment",
        expected_source_ids=["SYN-P003-PT-02"],
        prohibited_patient_ids=["SYN-P001", "SYN-P002"],
        category="contradictory",
        description="Topical match on PT offer; clinical content is refusal. Retrieval != verification.",
    ),
    ComparativeCase(
        case_id="EXP-07-SYNONYM-MISMATCH",
        patient_id="SYN-P001",
        query="ambulation assistance and non operative rehabilitation regimen",
        expected_source_ids=["SYN-P001-PT-02"],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="synonym_mismatch",
        description="Synonym mismatch: lexical BM25 fails (0 token overlap), dense embedding expected to bridge.",
    ),
    ComparativeCase(
        case_id="EXP-08-MULTIPLE-RELEVANT",
        patient_id="SYN-P001",
        query="persistent lumbar spine pain and clinical symptoms",
        expected_source_ids=["SYN-P001-NOTE-01", "SYN-P001-ORDER-03"],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="multiple_relevant",
        description="Multiple relevant sources: clinical note and MRI order both document lumbar pain.",
    ),
    ComparativeCase(
        case_id="EXP-09-ORDER-VS-EXAM",
        patient_id="SYN-P002",
        query="ordering clinician requisition for lumbar imaging study",
        expected_source_ids=["SYN-P002-ORDER-03"],
        prohibited_patient_ids=["SYN-P001", "SYN-P003"],
        category="order_requisition",
        description="Requisition intent targeting ORDER-03 over clinical examination notes.",
    ),
    ComparativeCase(
        case_id="EXP-10-EXPLICIT-NEGATION",
        patient_id="SYN-P001",
        query="bowel or bladder dysfunction sphincter changes",
        expected_source_ids=["SYN-P001-NOTE-01"],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="explicit_negation",
        description="Negative symptom documentation: NOTE-01 documents absence of bowel/bladder changes.",
    ),

    # Safety Invariant & Negative Controls (Empty Relevance Ground Truth)
    ComparativeCase(
        case_id="EXP-04-CROSS-PATIENT-ISOLATION",
        patient_id="SYN-P001",
        query="attended several sessions exact start date and duration are not documented",
        expected_source_ids=[],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="cross_patient",
        description="Safety invariant: query has exact text from SYN-P002. Zero foreign leakage permitted.",
    ),
    ComparativeCase(
        case_id="EXP-05-UNSUPPORTED-CRITERION",
        patient_id="SYN-P001",
        query="progressive motor deficit rapid motor weakness cauda equina",
        expected_source_ids=[],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="unsupported",
        description="Negative control: clinical chart has no cauda equina or progressive motor weakness.",
    ),
    ComparativeCase(
        case_id="EXP-06-ZERO-MATCH",
        patient_id="SYN-P001",
        query="coronary artery bypass graft cardiopulmonary bypass hemodynamics",
        expected_source_ids=[],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        category="zero_match",
        description="Negative control: completely unrelated cardiovascular surgical domain.",
    ),
]


@dataclass
class MethodEvaluationSummary:
    method_name: str
    quality_cases_count: int
    mean_precision_at_k: float
    mean_recall_at_k: float
    mrr: float
    cross_patient_violations: int
    all_safety_checks_passed: bool
    per_case_results: list[dict] = field(default_factory=list)


def evaluate_method_on_benchmark(
    session: Session,
    method_name: str,
    retrieval_fn,
    k: int = 3,
) -> MethodEvaluationSummary:
    """Evaluate a single retrieval method across the comparative benchmark cases."""
    precisions: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    case_results: list[dict] = []
    cross_patient_violations = 0
    all_safety_passed = True

    for case in COMPARATIVE_BENCHMARK_CASES:
        candidates = retrieval_fn(session, patient_id=case.patient_id, query=case.query, top_k=k)
        retrieved_sources = [c.source_id for c in candidates]
        retrieved_patients = [c.patient_id for c in candidates]

        leakage = any(p in case.prohibited_patient_ids for p in retrieved_patients)
        if leakage:
            cross_patient_violations += 1
            all_safety_passed = False

        expected_set = set(case.expected_source_ids)
        retrieved_set = set(retrieved_sources)

        if expected_set:
            is_safety = False
            safety_pass = not leakage

            tp = len(expected_set & retrieved_set)
            prec = tp / len(retrieved_sources) if retrieved_sources else 0.0
            rec = tp / len(expected_set)

            rr = 0.0
            for rank_idx, src in enumerate(retrieved_sources, start=1):
                if src in expected_set:
                    rr = 1.0 / rank_idx
                    break

            precisions.append(prec)
            recalls.append(rec)
            reciprocal_ranks.append(rr)

            p_out: float | None = round(prec, 4)
            r_out: float | None = round(rec, 4)
            rr_out: float | None = round(rr, 4)
        else:
            is_safety = True
            # For zero-match or cross-patient, pass requires zero foreign leakage and zero candidates
            # (or for unsupported, zero candidates if min_score filtered, or zero foreign leakage)
            safety_pass = not leakage and (len(retrieved_sources) == 0 if case.category != "unsupported" else True)
            if not safety_pass:
                all_safety_passed = False

            p_out = None
            r_out = None
            rr_out = None

        case_results.append({
            "case_id": case.case_id,
            "category": case.category,
            "query": case.query,
            "retrieved_sources": retrieved_sources,
            "expected_sources": case.expected_source_ids,
            "precision_at_k": p_out,
            "recall_at_k": r_out,
            "reciprocal_rank": rr_out,
            "cross_patient_leakage": leakage,
            "is_safety": is_safety,
            "safety_pass": safety_pass,
        })

    mean_prec = sum(precisions) / len(precisions) if precisions else 0.0
    mean_rec = sum(recalls) / len(recalls) if recalls else 0.0
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0

    return MethodEvaluationSummary(
        method_name=method_name,
        quality_cases_count=len(precisions),
        mean_precision_at_k=round(mean_prec, 4),
        mean_recall_at_k=round(mean_rec, 4),
        mrr=round(mrr, 4),
        cross_patient_violations=cross_patient_violations,
        all_safety_checks_passed=all_safety_passed,
        per_case_results=case_results,
    )


def run_comparative_retrieval_experiment(session: Session, k: int = 3) -> dict[str, MethodEvaluationSummary]:
    """Execute the full 3-way comparative experiment across BM25, Dense, and Hybrid retrieval."""
    bm25_summary = evaluate_method_on_benchmark(
        session, "BM25 (Baseline)", retrieve_chart_candidates, k=k
    )
    dense_summary = evaluate_method_on_benchmark(
        session, f"Dense ({MODEL_NAME})", retrieve_dense_chart_candidates, k=k
    )
    hybrid_summary = evaluate_method_on_benchmark(
        session, "Hybrid (BM25 + Dense RRF)", retrieve_hybrid_chart_candidates, k=k
    )

    return {
        "bm25": bm25_summary,
        "dense": dense_summary,
        "hybrid": hybrid_summary,
    }
