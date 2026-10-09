"""Integration tests for durable PostgreSQL persistence, transactions, and restart recovery."""
import os
import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    AuditLogModel,
    Base,
    CaseModel,
    CriterionResultModel,
    DocumentModel,
    PolicyCriterionModel,
    PolicyModel,
)
from backend.db.repository import PostgresCaseRepository
from backend.db.seed import seed_synthetic_data
from contracts.schemas import (
    CaseStatus,
    CriterionStatus,
    FinalizationActionRequest,
    FinalizationActionType,
    ReviewActionRequest,
    ReviewActionType,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class PostgresPersistenceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
        cls.SessionClass = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        # Reset tables for clean test isolation
        with self.SessionClass() as session:
            session.query(AuditLogModel).delete()
            session.query(CriterionResultModel).delete()
            session.query(CaseModel).delete()
            session.query(DocumentModel).delete()
            session.query(PolicyCriterionModel).delete()
            session.query(PolicyModel).delete()
            session.commit()
            seed_synthetic_data(session)
            session.commit()

        self.repo = PostgresCaseRepository(session_factory=self.SessionClass)

    def test_seeding_is_repeatable_and_preserves_relational_integrity(self):
        with self.SessionClass() as session:
            # Re-run seed on already seeded DB
            counts = seed_synthetic_data(session)
            session.commit()
            self.assertEqual(counts["policies"], 0)
            self.assertEqual(counts["cases"], 0)
            self.assertEqual(counts["documents"], 0)
            self.assertEqual(counts["results"], 0)

            # Verify integrity
            cases = session.query(CaseModel).all()
            self.assertEqual(len(cases), 3)
            for c in cases:
                self.assertIsNotNone(c.policy)
                self.assertEqual(len(c.criterion_results), 3)

    def test_review_action_persisted_in_audit_log(self):
        req = ReviewActionRequest(
            criterion_id="C2",
            action=ReviewActionType.REQUEST_INFORMATION,
            note="Requesting detailed therapy logs from physical therapist.",
        )
        res = self.repo.record_review("CASE-SYN-002", req)
        self.assertEqual(res.criterion_id, "C2")

        # Verify from completely separate database session
        with self.SessionClass() as session:
            case = session.query(CaseModel).filter_by(case_id="CASE-SYN-002").first()
            self.assertEqual(case.status, CaseStatus.IN_HUMAN_REVIEW.value)

            audit_rows = session.query(AuditLogModel).filter_by(case_id="CASE-SYN-002").all()
            self.assertEqual(len(audit_rows), 1)
            self.assertEqual(audit_rows[0].criterion_id, "C2")
            self.assertEqual(audit_rows[0].action, ReviewActionType.REQUEST_INFORMATION.value)
            self.assertEqual(audit_rows[0].note, req.note)
            self.assertIn("UNAUTHENTICATED_DEV", audit_rows[0].actor)

    def test_approval_and_rejection_state_persists(self):
        # 1. Approval persists
        approve_req = FinalizationActionRequest(
            action=FinalizationActionType.APPROVE_PACKET,
            reviewer_note="All criteria satisfied and verified.",
        )
        packet = self.repo.finalize_packet("CASE-SYN-001", approve_req)
        self.assertTrue(packet.finalized)

        with self.SessionClass() as session:
            c1 = session.query(CaseModel).filter_by(case_id="CASE-SYN-001").first()
            self.assertEqual(c1.status, CaseStatus.FINALIZED.value)
            self.assertIsNotNone(c1.finalized_at)

        # 2. Rejection persists
        reject_req = FinalizationActionRequest(
            action=FinalizationActionType.REJECT_PACKET,
            reviewer_note="Contraindication documented; prior authorization denied.",
        )
        reject_packet = self.repo.finalize_packet("CASE-SYN-003", reject_req)
        self.assertFalse(reject_packet.finalized)

        with self.SessionClass() as session:
            c3 = session.query(CaseModel).filter_by(case_id="CASE-SYN-003").first()
            self.assertEqual(c3.status, CaseStatus.REJECTED.value)

    def test_restart_recovery_demonstration(self):
        """Proof that saved case state and audit history survive complete application restart."""
        # 1. Mutate state with instance A
        repo_instance_a = PostgresCaseRepository(session_factory=self.SessionClass)
        review_req = ReviewActionRequest(
            criterion_id="C2",
            action=ReviewActionType.ACCEPT_GAP,
            note="Accepting documented 5-week PT trial given severe symptom progression.",
        )
        repo_instance_a.record_review("CASE-SYN-002", review_req)

        approve_req = FinalizationActionRequest(
            action=FinalizationActionType.APPROVE_PACKET,
            reviewer_note="Case approved following clinical review of gap.",
        )
        repo_instance_a.finalize_packet("CASE-SYN-002", approve_req)

        # 2. Simulate shutdown: destroy repo instance A and all references
        del repo_instance_a

        # 3. Instantiate fresh repo instance B (simulating cold process restart)
        repo_instance_b = PostgresCaseRepository(session_factory=self.SessionClass)

        # 4. Verify case state is recovered identically
        case = repo_instance_b.get_case("CASE-SYN-002")
        self.assertIsNotNone(case)
        self.assertEqual(case.status, CaseStatus.FINALIZED)

        packet = repo_instance_b.get_packet("CASE-SYN-002")
        self.assertIsNotNone(packet)
        self.assertTrue(packet.finalized)
        self.assertEqual(packet.reviewer_note, "Case approved following clinical review of gap.")

        # Verify audit history is intact
        with self.SessionClass() as session:
            audit_events = (
                session.query(AuditLogModel)
                .filter_by(case_id="CASE-SYN-002")
                .order_by(AuditLogModel.id)
                .all()
            )
            self.assertEqual(len(audit_events), 2)
            self.assertEqual(audit_events[0].action, ReviewActionType.ACCEPT_GAP.value)
            self.assertEqual(audit_events[1].action, "approve_packet")

    def test_failed_transaction_leaves_no_partial_records(self):
        with self.assertRaises(IntegrityError):
            with self.SessionClass() as session:
                # Violate foreign key constraint (non-existent policy)
                orphan_case = CaseModel(
                    case_id="CASE-ORPHAN",
                    patient_id="SYN-P999",
                    service="Lumbar MRI",
                    policy_id="NON_EXISTENT_POLICY",
                    status="RESULTS_READY",
                    scenario="test",
                )
                session.add(orphan_case)
                session.commit()

        # Confirm nothing was committed
        with self.SessionClass() as session:
            self.assertIsNone(session.query(CaseModel).filter_by(case_id="CASE-ORPHAN").first())


if __name__ == "__main__":
    unittest.main()
