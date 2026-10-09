"""Synthetic gold evaluation benchmark for AuthOS structured evidence verification.

IMPORTANT NOTICE:
This benchmark operates exclusively on synthetic records (SYN-P001, SYN-P002, SYN-P003).
It provides an empirical verification regression gate, NOT a clinical accuracy claim.

Covers the 12 non-negotiable verification scenarios:
1. Direct support.
2. Relevant terminology with insufficient factual support.
3. Explicit negation.
4. Contradictory evidence.
5. Missing information.
6. Ambiguous duration or timing.
7. Multiple passages needed to establish a criterion.
8. Conflicting statements with different dates.
9. Correct quotation attributed to the wrong patient.
10. Invalid or stale source offsets.
11. A retrieved passage that mentions the topic but does not establish the required fact.
12. A source containing an unsupported fact that must not be copied into the result.
"""
from dataclasses import dataclass, field
from contracts.schemas import CriterionResult, CriterionStatus, EvidencePolarity
from backend.verification.engine import verify_criterion_evidence

# Canonical synthetic documents for test isolation
SYN_P001_DOCS = [
    {
        "source_id": "SYN-P001-NOTE-01",
        "patient_id": "SYN-P001",
        "date": "2026-08-01",
        "text": "Patient reports low back pain for 10 weeks. No bowel or bladder changes reported.",
    },
    {
        "source_id": "SYN-P001-PT-02",
        "patient_id": "SYN-P001",
        "date": "2026-09-15",
        "text": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
    },
    {
        "source_id": "SYN-P001-ORDER-03",
        "patient_id": "SYN-P001",
        "date": "2026-09-18",
        "text": "Ordering clinician requests lumbar MRI for persistent low back pain following conservative treatment.",
    },
]

SYN_P002_DOCS = [
    {
        "source_id": "SYN-P002-NOTE-01",
        "patient_id": "SYN-P002",
        "date": "2026-08-04",
        "text": "Patient reports low back pain for approximately 2 months.",
    },
    {
        "source_id": "SYN-P002-PT-02",
        "patient_id": "SYN-P002",
        "date": "2026-09-02",
        "text": "Physical therapy was discussed. Patient attended several sessions; exact start date and duration are not documented.",
    },
    {
        "source_id": "SYN-P002-ORDER-03",
        "patient_id": "SYN-P002",
        "date": "2026-09-03",
        "text": "Lumbar MRI requested. Prior conservative-treatment duration requires clarification.",
    },
]

SYN_P003_DOCS = [
    {
        "source_id": "SYN-P003-NOTE-01",
        "patient_id": "SYN-P003",
        "date": "2026-08-10",
        "text": "Patient reports low back pain for 8 weeks.",
    },
    {
        "source_id": "SYN-P003-PT-02",
        "patient_id": "SYN-P003",
        "date": "2026-08-11",
        "text": "Physical therapy was offered. Patient declined physical therapy at this visit.",
    },
    {
        "source_id": "SYN-P003-ORDER-03",
        "patient_id": "SYN-P003",
        "date": "2026-08-12",
        "text": "Lumbar MRI requested. Documentation of completed conservative treatment is not present in the supplied chart.",
    },
]


@dataclass
class GoldVerificationCase:
    case_id: str
    name: str
    patient_id: str
    criterion_id: str
    criterion_text: str
    raw_documents: list[dict]
    candidate_evidence: list[dict]
    expected_status: CriterionStatus
    expected_verified: bool
    rationale: str
    min_duration_days: int | None = None
    required_facts: list[str] = field(default_factory=list)


GOLD_BENCHMARK_CASES: list[GoldVerificationCase] = [
    # 1. Direct support
    GoldVerificationCase(
        case_id="GOLD-01",
        name="Direct support",
        patient_id="SYN-P001",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P001_DOCS,
        min_duration_days=42,
        required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
        candidate_evidence=[
            {
                "source_id": "SYN-P001-PT-02",
                "patient_id": "SYN-P001",
                "quote": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
                "char_start": 0,
                "char_end": 108,
            }
        ],
        expected_status=CriterionStatus.MET,
        expected_verified=True,
        rationale="Exact verbatim quotation with valid offsets establishes completed supervised PT spanning July 1 - Aug 20 (50 days >= 42 days).",
    ),

    # 2. Relevant terminology with insufficient factual support
    GoldVerificationCase(
        case_id="GOLD-02",
        name="Relevant terminology with insufficient factual support",
        patient_id="SYN-P001",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P001_DOCS,
        min_duration_days=42,
        required_facts=["Duration >= 6 weeks"],
        candidate_evidence=[
            {
                "source_id": "SYN-P001-ORDER-03",
                "patient_id": "SYN-P001",
                "quote": "Ordering clinician requests lumbar MRI for persistent low back pain following conservative treatment.",
                "char_start": 0,
                "char_end": 101,
            }
        ],
        expected_status=CriterionStatus.AMBIGUOUS,
        expected_verified=False,
        rationale="Passage contains relevant keyword 'conservative treatment', but omits specific dates and duration needed to prove >= 6 weeks.",
    ),

    # 3. Explicit negation
    GoldVerificationCase(
        case_id="GOLD-03",
        name="Explicit negation",
        patient_id="SYN-P001",
        criterion_id="C_NEURO",
        criterion_text="Progressive neurological deficit or cauda equina syndrome documented",
        raw_documents=SYN_P001_DOCS,
        required_facts=["Bowel or bladder dysfunction"],
        candidate_evidence=[
            {
                "source_id": "SYN-P001-NOTE-01",
                "patient_id": "SYN-P001",
                "quote": "Patient reports low back pain for 10 weeks. No bowel or bladder changes reported.",
                "char_start": 0,
                "char_end": 81,
            }
        ],
        expected_status=CriterionStatus.CONTRADICTED,
        expected_verified=False,
        rationale="Passage contains explicit clinical negation ('No bowel or bladder changes reported'); cannot substantiate cauda equina.",
    ),

    # 4. Contradictory evidence
    GoldVerificationCase(
        case_id="GOLD-04",
        name="Contradictory evidence",
        patient_id="SYN-P003",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P003_DOCS,
        min_duration_days=42,
        required_facts=["Completed conservative treatment >= 6 weeks"],
        candidate_evidence=[
            {
                "source_id": "SYN-P003-PT-02",
                "patient_id": "SYN-P003",
                "quote": "Physical therapy was offered. Patient declined physical therapy at this visit.",
                "char_start": 0,
                "char_end": 78,
            }
        ],
        expected_status=CriterionStatus.CONTRADICTED,
        expected_verified=False,
        rationale="Passage explicitly records that patient declined physical therapy; directly contradicts completed conservative care.",
    ),

    # 5. Missing information
    GoldVerificationCase(
        case_id="GOLD-05",
        name="Missing information",
        patient_id="SYN-P003",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P003_DOCS,
        required_facts=["Documentation of completed conservative treatment"],
        candidate_evidence=[],  # No supporting evidence found in chart
        expected_status=CriterionStatus.MISSING,
        expected_verified=False,
        rationale="Zero supporting evidence found in chart. Unproven in supplied records (does not claim real-world event never happened).",
    ),

    # 6. Ambiguous duration or timing
    GoldVerificationCase(
        case_id="GOLD-06",
        name="Ambiguous duration or timing",
        patient_id="SYN-P002",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P002_DOCS,
        min_duration_days=42,
        required_facts=["Duration >= 6 weeks"],
        candidate_evidence=[
            {
                "source_id": "SYN-P002-PT-02",
                "patient_id": "SYN-P002",
                "quote": "Physical therapy was discussed. Patient attended several sessions; exact start date and duration are not documented.",
                "char_start": 0,
                "char_end": 116,
            }
        ],
        expected_status=CriterionStatus.AMBIGUOUS,
        expected_verified=False,
        rationale="Patient attended sessions, but exact start date and duration are explicitly undocumented; duration cannot be established.",
    ),

    # 7. Multiple passages needed to establish a criterion
    GoldVerificationCase(
        case_id="GOLD-07",
        name="Multiple passages needed to establish a criterion",
        patient_id="SYN-P001",
        criterion_id="C1",
        criterion_text="Documentation describes persistent low back symptoms",
        raw_documents=SYN_P001_DOCS,
        required_facts=["Low back pain", "Persistent symptoms"],
        candidate_evidence=[
            {
                "source_id": "SYN-P001-NOTE-01",
                "patient_id": "SYN-P001",
                "quote": "Patient reports low back pain for 10 weeks. No bowel or bladder changes reported.",
                "char_start": 0,
                "char_end": 81,
            },
            {
                "source_id": "SYN-P001-PT-02",
                "patient_id": "SYN-P001",
                "quote": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
                "char_start": 0,
                "char_end": 108,
            },
        ],
        expected_status=CriterionStatus.MET,
        expected_verified=True,
        rationale="Multiple authentic passages collectively establish low back pain and ongoing persistence across August and September.",
    ),

    # 8. Conflicting statements with different dates
    GoldVerificationCase(
        case_id="GOLD-08",
        name="Conflicting statements with different dates",
        patient_id="SYN-P001",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=[
            {
                "source_id": "SYN-P001-PLAN-01",
                "patient_id": "SYN-P001",
                "date": "2026-08-01",
                "text": "Physical therapy planned for 8 weeks.",
            },
            {
                "source_id": "SYN-P001-NOTE-02",
                "patient_id": "SYN-P001",
                "date": "2026-08-15",
                "text": "Patient discontinued physical therapy after 1 week due to work conflict.",
            },
        ],
        min_duration_days=42,
        required_facts=["Duration >= 6 weeks"],
        candidate_evidence=[
            {
                "source_id": "SYN-P001-PLAN-01",
                "patient_id": "SYN-P001",
                "quote": "Physical therapy planned for 8 weeks.",
                "char_start": 0,
                "char_end": 37,
            },
            {
                "source_id": "SYN-P001-NOTE-02",
                "patient_id": "SYN-P001",
                "quote": "Patient discontinued physical therapy after 1 week due to work conflict.",
                "char_start": 0,
                "char_end": 72,
            },
        ],
        expected_status=CriterionStatus.CONTRADICTED,
        expected_verified=False,
        rationale="Early treatment plan conflicts with subsequent progress note documenting early discontinuation at 1 week.",
    ),

    # 9. Correct quotation attributed to the wrong patient
    GoldVerificationCase(
        case_id="GOLD-09",
        name="Correct quotation attributed to the wrong patient",
        patient_id="SYN-P002",  # Target patient is SYN-P002
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P002_DOCS,
        min_duration_days=42,
        candidate_evidence=[
            {
                # Quote is from SYN-P001, claimed against SYN-P002
                "source_id": "SYN-P001-PT-02",
                "patient_id": "SYN-P001",
                "quote": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
                "char_start": 0,
                "char_end": 109,
            }
        ],
        expected_status=CriterionStatus.MISSING,
        expected_verified=False,
        rationale="Cross-patient provenance violation: source belongs to SYN-P001, completely rejected for patient SYN-P002.",
    ),

    # 10. Invalid or stale source offsets
    GoldVerificationCase(
        case_id="GOLD-10",
        name="Invalid or stale source offsets",
        patient_id="SYN-P001",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P001_DOCS,
        min_duration_days=42,
        candidate_evidence=[
            {
                "source_id": "SYN-P001-PT-02",
                "patient_id": "SYN-P001",
                # Quote does not match slice [0:15] ('Patient complet')
                "quote": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
                "char_start": 0,
                "char_end": 15,
            }
        ],
        expected_status=CriterionStatus.MISSING,
        expected_verified=False,
        rationale="Offset mismatch: text[0:15] does not equal quote. Stale or fabricated offsets are rejected.",
    ),

    # 11. A retrieved passage that mentions the topic but does not establish the required fact
    GoldVerificationCase(
        case_id="GOLD-11",
        name="A retrieved passage that mentions the topic but does not establish the required fact",
        patient_id="SYN-P002",
        criterion_id="C2",
        criterion_text="Conservative treatment history is documented for at least six weeks",
        raw_documents=SYN_P002_DOCS,
        min_duration_days=42,
        required_facts=["Duration >= 6 weeks"],
        candidate_evidence=[
            {
                "source_id": "SYN-P002-ORDER-03",
                "patient_id": "SYN-P002",
                "quote": "Lumbar MRI requested. Prior conservative-treatment duration requires clarification.",
                "char_start": 0,
                "char_end": 83,
            }
        ],
        expected_status=CriterionStatus.AMBIGUOUS,
        expected_verified=False,
        rationale="Retrieved requisition mentions conservative-treatment duration, but explicitly notes it requires clarification.",
    ),

    # 12. A source containing an unsupported fact that must not be copied into the result
    GoldVerificationCase(
        case_id="GOLD-12",
        name="A source containing an unsupported fact that must not be copied into the result",
        patient_id="SYN-P001",
        criterion_id="C_SURGERY",
        criterion_text="Prior lumbar spinal fusion surgery documented",
        raw_documents=SYN_P001_DOCS,
        required_facts=["Spinal fusion surgery"],
        candidate_evidence=[
            {
                # Trying to cite NOTE-01 which has no mention of surgery
                "source_id": "SYN-P001-NOTE-01",
                "patient_id": "SYN-P001",
                "quote": "Patient reports low back pain for 10 weeks. No bowel or bladder changes reported.",
                "char_start": 0,
                "char_end": 81,
            }
        ],
        expected_status=CriterionStatus.MISSING,
        expected_verified=False,
        rationale="NOTE-01 does not mention spinal fusion surgery. System refuses to mark MET or copy ungrounded assertions.",
    ),
]


@dataclass
class VerificationBenchmarkSummary:
    total_cases: int
    correct_statuses: int
    accuracy: float
    confusion_matrix: dict[str, dict[str, int]]
    results: list[dict] = field(default_factory=list)


def run_gold_verification_benchmark() -> VerificationBenchmarkSummary:
    """Run all 12 synthetic gold verification cases and report accuracy and confusion counts."""
    correct = 0
    statuses = ["MET", "AMBIGUOUS", "CONTRADICTED", "MISSING"]
    confusion: dict[str, dict[str, int]] = {s: {s2: 0 for s2 in statuses} for s in statuses}
    results: list[dict] = []

    for case in GOLD_BENCHMARK_CASES:
        res: CriterionResult = verify_criterion_evidence(
            criterion_id=case.criterion_id,
            criterion_text=case.criterion_text,
            patient_id=case.patient_id,
            candidate_evidence=case.candidate_evidence,
            raw_documents=case.raw_documents,
            required_facts=case.required_facts,
            min_duration_days=case.min_duration_days,
        )

        is_match = (res.status == case.expected_status) and (res.verified == case.expected_verified)
        if is_match:
            correct += 1

        exp_str = case.expected_status.value
        act_str = res.status.value
        confusion[exp_str][act_str] = confusion[exp_str].get(act_str, 0) + 1

        results.append({
            "case_id": case.case_id,
            "name": case.name,
            "expected_status": exp_str,
            "actual_status": act_str,
            "expected_verified": case.expected_verified,
            "actual_verified": res.verified,
            "is_match": is_match,
            "validator_flags": res.validator_flags,
            "reason": res.reason,
            "rationale": case.rationale,
        })

    accuracy = correct / len(GOLD_BENCHMARK_CASES) if GOLD_BENCHMARK_CASES else 0.0

    return VerificationBenchmarkSummary(
        total_cases=len(GOLD_BENCHMARK_CASES),
        correct_statuses=correct,
        accuracy=round(accuracy, 4),
        confusion_matrix=confusion,
        results=results,
    )
