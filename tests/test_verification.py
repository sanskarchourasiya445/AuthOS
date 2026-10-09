"""Unit and adversarial verification tests for AuthOS structured evidence verification (Phase 2C).

Enforces invariants:
1. Retrieval score/similarity/rank != verification.
2. Invariant: raw_source_text[char_start:char_end] == quote verbatim.
3. Provenance validation rejects cross-patient data, invalid offsets, and altered quotes.
4. Deterministic negation and contradiction detection flags explicit refusals.
5. Inconclusive or conflicting evidence defaults to AMBIGUOUS or CONTRADICTED with review_required=True.
6. Schema safety rejects MET status with unresolved conflicting evidence.
7. Gold benchmark achieves 100% on the 12 non-negotiable scenarios with zero false positives.
8. Deterministic repeatability over 50 iterations.
"""
import unittest
from contracts.schemas import (
    CriterionResult,
    CriterionStatus,
    EvidenceItem,
    EvidencePolarity,
)
from pydantic import ValidationError
from backend.verification.engine import (
    validate_evidence_provenance,
    detect_evidence_polarity,
    verify_criterion_evidence,
)
from backend.verification.gold_evaluation import (
    run_gold_verification_benchmark,
    SYN_P001_DOCS,
    SYN_P002_DOCS,
    SYN_P003_DOCS,
)


class VerificationEngineTests(unittest.TestCase):
    """Adversarial and boundary verification tests."""

    def test_gold_benchmark_12_cases(self):
        """Synthetic gold evaluation benchmark achieves 100% accuracy and zero false positives."""
        summary = run_gold_verification_benchmark()
        self.assertEqual(summary.total_cases, 12)
        self.assertEqual(summary.correct_statuses, 12)
        self.assertEqual(summary.accuracy, 1.0)

        # Zero false positives: when expected is not MET, actual must never be MET
        for r in summary.results:
            if r["expected_status"] != "MET":
                self.assertNotEqual(
                    r["actual_status"],
                    "MET",
                    f"False positive on case {r['case_id']}: expected {r['expected_status']} but got MET"
                )

    def test_retrieval_candidate_does_not_imply_verification(self):
        """A retrieved candidate passage with high similarity does NOT mark criterion MET."""
        # Simulated retrieved chunk that mentions the topic but lacks duration
        candidate = {
            "source_id": "SYN-P001-ORDER-03",
            "patient_id": "SYN-P001",
            "quote": "Ordering clinician requests lumbar MRI for persistent low back pain following conservative treatment.",
            "char_start": 0,
            "char_end": 101,
        }
        res = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks",
            patient_id="SYN-P001",
            candidate_evidence=[candidate],
            raw_documents=SYN_P001_DOCS,
            min_duration_days=42,
        )
        self.assertFalse(res.verified)
        self.assertEqual(res.status, CriterionStatus.AMBIGUOUS)
        self.assertTrue(res.review_required)
        self.assertIn("Documentation of completed treatment duration of at least 6 weeks", res.missing_facts)

    def test_verbatim_offset_mismatch_rejected(self):
        """Stale or fabricated character offsets cause provenance failure and rejection."""
        # Intentionally wrong offsets (0 to 20 instead of 0 to 108)
        bad_candidate = {
            "source_id": "SYN-P001-PT-02",
            "patient_id": "SYN-P001",
            "quote": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
            "char_start": 0,
            "char_end": 20,
        }
        is_valid, reasons, _, _, _ = validate_evidence_provenance(
            bad_candidate, patient_id="SYN-P001", raw_documents=SYN_P001_DOCS
        )
        self.assertFalse(is_valid)
        self.assertIn("OFFSET_MISMATCH", reasons)

        res = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks",
            patient_id="SYN-P001",
            candidate_evidence=[bad_candidate],
            raw_documents=SYN_P001_DOCS,
            min_duration_days=42,
        )
        self.assertFalse(res.verified)
        self.assertEqual(res.status, CriterionStatus.MISSING)

    def test_cross_patient_evidence_attribution_rejected(self):
        """Evidence from another patient's chart is rejected by provenance validation."""
        foreign_candidate = {
            "source_id": "SYN-P001-PT-02",
            "patient_id": "SYN-P001",
            "quote": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
            "char_start": 0,
            "char_end": 108,
        }
        # Evaluating for patient SYN-P002 with SYN-P002's documents
        is_valid, reasons, _, _, _ = validate_evidence_provenance(
            foreign_candidate, patient_id="SYN-P002", raw_documents=SYN_P002_DOCS
        )
        self.assertFalse(is_valid)
        self.assertIn("SOURCE_NOT_FOUND", reasons)

        res = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks",
            patient_id="SYN-P002",
            candidate_evidence=[foreign_candidate],
            raw_documents=SYN_P002_DOCS,
            min_duration_days=42,
        )
        self.assertFalse(res.verified)
        self.assertEqual(res.status, CriterionStatus.MISSING)

    def test_explicit_treatment_refusal_classified_contradicted(self):
        """Declined or refused therapy must be classified as CONTRADICTED, never MET."""
        declined_candidate = {
            "source_id": "SYN-P003-PT-02",
            "patient_id": "SYN-P003",
            "quote": "Physical therapy was offered. Patient declined physical therapy at this visit.",
            "char_start": 0,
            "char_end": 78,
        }
        res = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks",
            patient_id="SYN-P003",
            candidate_evidence=[declined_candidate],
            raw_documents=SYN_P003_DOCS,
            min_duration_days=42,
        )
        self.assertFalse(res.verified)
        self.assertEqual(res.status, CriterionStatus.CONTRADICTED)
        self.assertTrue(res.review_required)
        self.assertEqual(res.evidence[0].polarity, EvidencePolarity.CONTRADICTING)

    def test_conflicting_dated_evidence_detected(self):
        """Conflicting statements from different dates cause CONTRADICTED status with review_required."""
        docs = [
            {"source_id": "SYN-P001-PLAN", "patient_id": "SYN-P001", "date": "2026-08-01", "text": "Physical therapy planned for 8 weeks."},
            {"source_id": "SYN-P001-NOTE", "patient_id": "SYN-P001", "date": "2026-08-15", "text": "Patient discontinued physical therapy after 1 week due to work conflict."},
        ]
        candidates = [
            {"source_id": "SYN-P001-PLAN", "patient_id": "SYN-P001", "quote": "Physical therapy planned for 8 weeks.", "char_start": 0, "char_end": 37},
            {"source_id": "SYN-P001-NOTE", "patient_id": "SYN-P001", "quote": "Patient discontinued physical therapy after 1 week due to work conflict.", "char_start": 0, "char_end": 72},
        ]
        res = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks",
            patient_id="SYN-P001",
            candidate_evidence=candidates,
            raw_documents=docs,
            min_duration_days=42,
        )
        self.assertFalse(res.verified)
        self.assertEqual(res.status, CriterionStatus.CONTRADICTED)
        self.assertTrue(res.review_required)
        self.assertIn("CONFLICTING_EVIDENCE_DETECTED", res.validator_flags)
        self.assertTrue(len(res.conflicting_evidence) > 0)

    def test_schema_validator_rejects_met_with_conflicting_evidence(self):
        """Schema-level invariant: MET status cannot be saved with unresolved conflicting evidence."""
        evidence_item = EvidenceItem(
            source_id="SYN-P001-PT-02",
            patient_id="SYN-P001",
            quote="Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
            char_start=0,
            char_end=108,
            polarity=EvidencePolarity.SUPPORTING,
        )
        conflict_item = EvidenceItem(
            source_id="SYN-P001-NOTE-02",
            patient_id="SYN-P001",
            quote="Patient discontinued physical therapy after 1 week.",
            char_start=0,
            char_end=50,
            polarity=EvidencePolarity.CONTRADICTING,
        )

        with self.assertRaises(ValidationError) as ctx:
            CriterionResult(
                criterion_id="C2",
                criterion_text="Conservative treatment history is documented for at least six weeks",
                status=CriterionStatus.MET,
                verified=True,
                evidence=[evidence_item],
                conflicting_evidence=[conflict_item],  # Violates safety validator
                reason="Cannot be MET with unresolved conflicting evidence",
            )
        self.assertIn("A MET criterion result cannot have unresolved conflicting_evidence", str(ctx.exception))

    def test_deterministic_repeatability(self):
        """Running verification 50 times yields 100% identical outputs."""
        candidate = {
            "source_id": "SYN-P001-PT-02",
            "patient_id": "SYN-P001",
            "quote": "Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms.",
            "char_start": 0,
            "char_end": 108,
        }
        baseline = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks",
            patient_id="SYN-P001",
            candidate_evidence=[candidate],
            raw_documents=SYN_P001_DOCS,
            min_duration_days=42,
        )

        for _ in range(50):
            trial = verify_criterion_evidence(
                criterion_id="C2",
                criterion_text="Conservative treatment history is documented for at least six weeks",
                patient_id="SYN-P001",
                candidate_evidence=[candidate],
                raw_documents=SYN_P001_DOCS,
                min_duration_days=42,
            )
            self.assertEqual(baseline.status, trial.status)
            self.assertEqual(baseline.verified, trial.verified)
            self.assertEqual(baseline.validator_flags, trial.validator_flags)
            self.assertEqual(baseline.reason, trial.reason)
            self.assertEqual(baseline.missing_facts, trial.missing_facts)


if __name__ == "__main__":
    unittest.main()
