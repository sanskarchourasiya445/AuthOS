"""Evaluation harness and synthetic benchmark for AuthOS retrieval baseline.

IMPORTANT LIMITATION NOTICE:
This evaluation operates strictly over synthetic fixture data (SYN-P001, SYN-P002, SYN-P003).
It is designed as a deterministic synthetic smoke test and regression verification harness,
NOT as a clinical efficacy benchmark or proof of generalizable real-world IR performance.

METRIC CONVENTIONS & INTEGRITY:
- Relevance Unit: Source document identifier (`source_id`), as clinical ground truth in the
  synthetic fixture is documented at the source note level.
- Retrieval Quality Cases: Queries with non-empty ground-truth relevance sets (`expected_source_ids`).
  Precision@k, Recall@k, and MRR are computed exclusively over these cases.
- Safety Invariant Checks: Negative controls, cross-patient isolation tests, and zero-match domains.
  These have empty ground-truth sets and are evaluated as binary safety passes (0 foreign leakage,
  0 ungrounded candidates). They are NEVER padded with artificial 1.0 scores into IR averages.
"""
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from backend.rag.retrieval import retrieve_chart_candidates


@dataclass
class EvalCase:
    case_id: str
    patient_id: str
    criterion_id: str | None
    query: str
    expected_source_ids: list[str]
    prohibited_patient_ids: list[str]
    description: str
    category: str  # 'relevant', 'irrelevant_match', 'contradictory', 'cross_patient', 'unsupported', 'zero_match'


@dataclass
class EvalCaseResult:
    case_id: str
    category: str
    query: str
    patient_id: str
    retrieved_chunk_ids: list[str]
    retrieved_source_ids: list[str]
    expected_source_ids: list[str]
    precision_at_k: float | None
    recall_at_k: float | None
    reciprocal_rank: float | None
    cross_patient_leakage: bool
    is_safety_check: bool
    safety_pass: bool
    notes: str


@dataclass
class BenchmarkReport:
    total_cases: int
    quality_cases_count: int
    safety_cases_count: int
    mean_precision_at_k: float
    mean_recall_at_k: float
    mrr: float
    cross_patient_violations: int
    all_safety_checks_passed: bool
    case_results: list[EvalCaseResult] = field(default_factory=list)


# Synthetic evaluation benchmark cases
SYNTHETIC_EVAL_CASES: list[EvalCase] = [
    # --- Retrieval Quality Benchmarks (Positive Ground Truth) ---
    EvalCase(
        case_id="EVAL-01-RELEVANT",
        patient_id="SYN-P001",
        criterion_id="C2",
        query="Conservative treatment history is documented for at least six weeks physical therapy",
        expected_source_ids=["SYN-P001-PT-02"],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        description="Expected relevant evidence: physical therapy note documenting 7+ weeks of conservative therapy.",
        category="relevant",
    ),
    EvalCase(
        case_id="EVAL-02-IRRELEVANT-KEYWORD",
        patient_id="SYN-P001",
        criterion_id="C1",
        query="low back pain persistent symptoms duration",
        expected_source_ids=["SYN-P001-NOTE-01"],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        description="Plausible keyword overlap: clinical note documents symptom duration, whereas order note also contains 'low back pain' keyword.",
        category="irrelevant_match",
    ),
    EvalCase(
        case_id="EVAL-03-CONTRADICTORY",
        patient_id="SYN-P003",
        criterion_id="C2",
        query="physical therapy offered conservative treatment",
        expected_source_ids=["SYN-P003-PT-02"],
        prohibited_patient_ids=["SYN-P001", "SYN-P002"],
        description="Contradictory evidence: chart documents that patient declined PT. Lexically matches query, but semantically contradicts requirement.",
        category="contradictory",
    ),

    # --- Safety Invariants & Negative Controls (Empty Relevance Ground Truth) ---
    EvalCase(
        case_id="EVAL-04-CROSS-PATIENT-ISOLATION",
        patient_id="SYN-P001",
        criterion_id="C2",
        query="attended several sessions exact start date and duration are not documented",
        expected_source_ids=[],  # Text is from SYN-P002, must NEVER be returned for SYN-P001
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        description="Cross-patient isolation check: query contains exact verbatim terms from SYN-P002. SYN-P001 retrieval must return 0 foreign records.",
        category="cross_patient",
    ),
    EvalCase(
        case_id="EVAL-05-UNSUPPORTED-CRITERION",
        patient_id="SYN-P001",
        criterion_id="C_UNMET",
        query="progressive motor deficit rapid motor weakness cauda equina",
        expected_source_ids=[],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        description="Unsupported clinical criterion: no patient record describes motor deficit or cauda equina.",
        category="unsupported",
    ),
    EvalCase(
        case_id="EVAL-06-ZERO-MATCH",
        patient_id="SYN-P001",
        criterion_id=None,
        query="coronary artery bypass graft cardiopulmonary bypass hemodynamics",
        expected_source_ids=[],
        prohibited_patient_ids=["SYN-P002", "SYN-P003"],
        description="Zero match query: completely unrelated clinical domain producing zero candidates.",
        category="zero_match",
    ),
]


def run_retrieval_benchmark(session: Session, k: int = 3) -> BenchmarkReport:
    """Run the synthetic retrieval benchmark suite and return honest, unpadded metrics.

    Separates IR quality queries (queries with known relevant sources) from safety-invariant
    checks (cross-patient isolation, unsupported controls, zero-match queries).
    """
    results: list[EvalCaseResult] = []
    quality_precisions: list[float] = []
    quality_recalls: list[float] = []
    quality_reciprocal_ranks: list[float] = []

    cross_patient_violations = 0
    all_safety_passed = True

    for case in SYNTHETIC_EVAL_CASES:
        candidates = retrieve_chart_candidates(
            session,
            patient_id=case.patient_id,
            query=case.query,
            top_k=k,
        )

        retrieved_sources = [c.source_id for c in candidates]
        retrieved_chunk_ids = [c.chunk_id for c in candidates]
        retrieved_patient_ids = [c.patient_id for c in candidates]

        # Safety Check: Cross-patient leakage detection
        leakage = any(p in case.prohibited_patient_ids for p in retrieved_patient_ids)
        if leakage:
            cross_patient_violations += 1
            all_safety_passed = False

        expected_set = set(case.expected_source_ids)
        retrieved_set = set(retrieved_sources)

        if expected_set:
            # Positive ground-truth retrieval quality case
            is_safety = False
            safety_pass = not leakage

            tp = len(expected_set & retrieved_set)
            prec = tp / len(retrieved_sources) if retrieved_sources else 0.0
            rec = tp / len(expected_set)

            # Reciprocal rank (first position of an expected relevant item)
            rr = 0.0
            for rank_idx, src in enumerate(retrieved_sources, start=1):
                if src in expected_set:
                    rr = 1.0 / rank_idx
                    break

            quality_precisions.append(prec)
            quality_recalls.append(rec)
            quality_reciprocal_ranks.append(rr)

            p_out: float | None = round(prec, 4)
            r_out: float | None = round(rec, 4)
            rr_out: float | None = round(rr, 4)
        else:
            # Safety invariant / negative control: ground truth is empty
            is_safety = True
            # Safety pass requires zero foreign leakage and zero false-positive candidates
            safety_pass = (not leakage) and (len(retrieved_sources) == 0)
            if not safety_pass:
                all_safety_passed = False

            # Metrics for empty relevance sets are undefined (N/A); do NOT pad with 1.0!
            p_out = None
            r_out = None
            rr_out = None

        notes = ""
        if case.category == "contradictory":
            notes = (
                f"Retrieved {retrieved_sources}. WARNING: Passages lexically match query "
                f"but contain clinical contradiction (treatment declined). "
                f"Must NOT be marked as MET without downstream semantic verification."
            )
        elif case.category == "cross_patient":
            notes = (
                f"Cross-patient invariant: Foreign leakage={leakage}. "
                f"Retrieved foreign records count: {len(retrieved_sources)}."
            )
        elif case.category == "unsupported":
            notes = (
                f"Negative control: 0 candidates expected for unmentioned condition. "
                f"Candidates retrieved: {len(retrieved_sources)}."
            )
        elif case.category == "zero_match":
            notes = f"Zero matches expected and returned: {len(retrieved_sources) == 0}."

        results.append(
            EvalCaseResult(
                case_id=case.case_id,
                category=case.category,
                query=case.query,
                patient_id=case.patient_id,
                retrieved_chunk_ids=retrieved_chunk_ids,
                retrieved_source_ids=retrieved_sources,
                expected_source_ids=case.expected_source_ids,
                precision_at_k=p_out,
                recall_at_k=r_out,
                reciprocal_rank=rr_out,
                cross_patient_leakage=leakage,
                is_safety_check=is_safety,
                safety_pass=safety_pass,
                notes=notes,
            )
        )

    # Compute means strictly over retrieval quality cases (no artificial inflation)
    mean_prec = (
        sum(quality_precisions) / len(quality_precisions)
        if quality_precisions else 0.0
    )
    mean_rec = (
        sum(quality_recalls) / len(quality_recalls)
        if quality_recalls else 0.0
    )
    mrr = (
        sum(quality_reciprocal_ranks) / len(quality_reciprocal_ranks)
        if quality_reciprocal_ranks else 0.0
    )

    quality_count = len(quality_precisions)
    safety_count = len(SYNTHETIC_EVAL_CASES) - quality_count

    return BenchmarkReport(
        total_cases=len(SYNTHETIC_EVAL_CASES),
        quality_cases_count=quality_count,
        safety_cases_count=safety_count,
        mean_precision_at_k=round(mean_prec, 4),
        mean_recall_at_k=round(mean_rec, 4),
        mrr=round(mrr, 4),
        cross_patient_violations=cross_patient_violations,
        all_safety_checks_passed=all_safety_passed,
        case_results=results,
    )
