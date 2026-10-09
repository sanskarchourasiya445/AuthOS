"""Tests for Pydantic v2 schemas and contract validation."""
import unittest
from pydantic import ValidationError
from contracts.schemas import (
    Criterion,
    EvidenceItem,
    RetryLogEntry,
    CriterionResult,
    CriterionStatus,
    CaseStatus,
    ReviewActionRequest,
    ReviewActionType,
    FinalizationActionRequest,
    FinalizationActionType,
    ReviewPacket,
    PacketCriterionRow,
    Case,
    CaseResultsResponse,
    ErrorCode,
    ErrorEnvelope,
    ErrorDetail,
)


class SchemaContractTests(unittest.TestCase):
    def test_valid_evidence_item(self):
        item = EvidenceItem(
            source_id="SYN-P001-PT-02",
            patient_id="SYN-P001",
            quote="Patient completed supervised physical therapy.",
            document_date="2026-09-15",
            retrieval_round=1,
        )
        self.assertEqual(item.source_id, "SYN-P001-PT-02")
        self.assertEqual(item.retrieval_round, 1)

    def test_valid_retry_log_entry(self):
        entry = RetryLogEntry(
            round=1,
            query="conservative treatment 6 weeks",
            found=["treatment_type"],
            missing=["duration"],
            sufficient=False,
        )
        self.assertEqual(entry.round, 1)
        self.assertFalse(entry.sufficient)

    def test_valid_criterion_result_met(self):
        ev = EvidenceItem(
            source_id="SYN-P001-PT-02",
            patient_id="SYN-P001",
            quote="Patient completed supervised physical therapy.",
            document_date="2026-09-15",
        )
        res = CriterionResult(
            criterion_id="C2",
            status=CriterionStatus.MET,
            verified=True,
            evidence=[ev],
            missing_facts=[],
            retry_log=[],
            validator_flags=[],
            reason="Verified PT notes covering required duration.",
        )
        self.assertEqual(res.status, CriterionStatus.MET)
        self.assertTrue(res.verified)
        self.assertEqual(len(res.evidence), 1)

    def test_met_status_requires_verified_true(self):
        ev = EvidenceItem(
            source_id="SYN-P001-PT-02",
            patient_id="SYN-P001",
            quote="Patient completed supervised physical therapy.",
            document_date="2026-09-15",
        )
        with self.assertRaises(ValidationError) as ctx:
            CriterionResult(
                criterion_id="C2",
                status=CriterionStatus.MET,
                verified=False,  # Invalid: MET must be verified
                evidence=[ev],
            )
        self.assertIn("A MET criterion result must have verified=True", str(ctx.exception))

    def test_met_status_requires_evidence(self):
        with self.assertRaises(ValidationError) as ctx:
            CriterionResult(
                criterion_id="C2",
                status=CriterionStatus.MET,
                verified=True,
                evidence=[],  # Invalid: MET must have at least one supporting evidence item
            )
        self.assertIn("A MET criterion result must have at least one supporting evidence item", str(ctx.exception))

    def test_met_status_rejects_missing_facts(self):
        ev = EvidenceItem(
            source_id="SYN-P001-PT-02",
            patient_id="SYN-P001",
            quote="Patient completed supervised physical therapy.",
            document_date="2026-09-15",
        )
        with self.assertRaises(ValidationError) as ctx:
            CriterionResult(
                criterion_id="C2",
                status=CriterionStatus.MET,
                verified=True,
                evidence=[ev],
                missing_facts=["duration"],  # Invalid: MET cannot have missing facts
            )
        self.assertIn("A MET criterion result cannot have missing_facts", str(ctx.exception))

    def test_non_met_status_must_have_verified_false(self):
        ev = EvidenceItem(
            source_id="SYN-P002-PT-02",
            patient_id="SYN-P002",
            quote="PT discussed.",
            document_date="2026-09-02",
        )
        with self.assertRaises(ValidationError) as ctx:
            CriterionResult(
                criterion_id="C2",
                status=CriterionStatus.AMBIGUOUS,
                verified=True,  # Invalid: Non-MET cannot be marked as verified positive
                evidence=[ev],
            )
        self.assertIn("A non-MET criterion result must have verified=False", str(ctx.exception))

    def test_forbid_extra_fields(self):
        with self.assertRaises(ValidationError):
            EvidenceItem(
                source_id="SYN-P001-PT-02",
                patient_id="SYN-P001",
                quote="Patient completed supervised physical therapy.",
                document_date="2026-09-15",
                unrecognized_field="unexpected",
            )

    def test_whitespace_stripped(self):
        item = EvidenceItem(
            source_id="  SYN-P001-PT-02  ",
            patient_id=" SYN-P001 ",
            quote=" Patient completed supervised physical therapy. ",
            document_date=" 2026-09-15 ",
        )
        self.assertEqual(item.source_id, "SYN-P001-PT-02")
        self.assertEqual(item.patient_id, "SYN-P001")
        self.assertEqual(item.quote, "Patient completed supervised physical therapy.")

    def test_review_action_validation(self):
        action = ReviewActionRequest(
            criterion_id="C2",
            action=ReviewActionType.REQUEST_INFORMATION,
            note="Please attach records showing exact duration.",
        )
        self.assertEqual(action.action, ReviewActionType.REQUEST_INFORMATION)

        with self.assertRaises(ValidationError):
            ReviewActionRequest(
                criterion_id="C2",
                action="invalid_action_string",  # Must be valid enum
                note="Note",
            )

    def test_finalization_action_validation(self):
        action = FinalizationActionRequest(
            action=FinalizationActionType.APPROVE_PACKET,
            reviewer_note="All criteria reviewed and verified.",
        )
        self.assertEqual(action.action, FinalizationActionType.APPROVE_PACKET)

        with self.assertRaises(ValidationError):
            FinalizationActionRequest(
                action="invalid_action",
                reviewer_note="Note",
            )

    def test_review_packet_validation(self):
        packet = ReviewPacket(
            case_id="CASE-SYN-001",
            patient_id="SYN-P001",
            criteria=[
                PacketCriterionRow(
                    criterion_id="C1",
                    criterion="Persistent low back symptoms",
                    status=CriterionStatus.MET,
                    evidence=[],
                    reason="Documented in note",
                    review_required=False,
                )
            ],
            finalized=False,
        )
        self.assertEqual(packet.packet_type, "SYNTHETIC_DEMO_REVIEW_PACKET")
        self.assertFalse(packet.finalized)

    def test_empty_strings_rejected_on_evidence_item(self):
        with self.assertRaises(ValidationError):
            EvidenceItem(
                source_id="",  # min_length=1
                patient_id="SYN-P001",
                quote="Some quote",
            )
        with self.assertRaises(ValidationError):
            EvidenceItem(
                source_id="SOURCE-1",
                patient_id="SYN-P001",
                quote="",  # min_length=1
            )

    def test_invalid_status_enum_rejected(self):
        ev = EvidenceItem(
            source_id="SYN-P001-PT-02",
            patient_id="SYN-P001",
            quote="Patient completed supervised physical therapy.",
            document_date="2026-09-15",
        )
        with self.assertRaises(ValidationError):
            CriterionResult(
                criterion_id="C2",
                status="APPROVED",  # Not a valid CriterionStatus enum
                verified=True,
                evidence=[ev],
            )


if __name__ == "__main__":
    unittest.main()
