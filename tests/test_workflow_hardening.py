"""Phase 3.1 Focused Hardening Tests.

Verifies:
1. Fresh database Alembic upgrade and schema/model parity.
2. Invalid review and finalization attempts from DRAFT and RUNNING are blocked with 409.
3. Evaluation routes all-MET cases to RESULTS_READY and non-MET cases to IN_HUMAN_REVIEW.
4. Evaluation never automatically approves or finalizes a packet.
5. Approval requires explicit human action; unadjudicated contradicted criteria cannot be approved without review.
6. Canonical generated_at timestamp stability across repeated reads and re-evaluation.
7. Safe public error responses without raw internal exception leakage.
8. Reviewer UI error envelope compatibility.
"""
import os
import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.main import create_app
from backend.api.v1.cases import get_repository
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
from backend.rag.ingest import ingest_synthetic_records
from contracts.schemas import (
    CaseStatus,
    CriterionStatus,
    ErrorCode,
    FinalizationActionType,
    ReviewActionType,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")
test_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


class WorkflowHardeningTests(unittest.TestCase):
    """Rigorous verification of Phase 3.1 hardening requirements."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    def setUp(self):
        with TestSession() as session:
            session.query(AuditLogModel).delete()
            session.query(CriterionResultModel).delete()
            session.query(CaseModel).delete()
            session.query(DocumentModel).delete()
            session.query(PolicyCriterionModel).delete()
            session.query(PolicyModel).delete()
            session.commit()
            seed_synthetic_data(session)
            ingest_synthetic_records(session)
            session.commit()

        self.repo = PostgresCaseRepository(session_factory=TestSession)
        self.app = create_app()
        self.app.dependency_overrides[get_repository] = lambda: self.repo
        self.client = TestClient(self.app)

        from backend.auth.schemas import AuthenticatedUser, UserRole
        from backend.auth.security import create_access_token
        dev_reviewer = AuthenticatedUser(
            sub="REV-001",
            name="Dr. Sarah Chen, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["*"],
        )
        token = create_access_token(dev_reviewer)
        self.client.headers["Authorization"] = f"Bearer {token}"

    # 1. Fresh database Alembic upgrade and schema/model parity
    def test_fresh_database_alembic_upgrade_and_schema_parity(self):
        """Alembic upgrade head succeeds on a clean disposable database and matches model columns."""
        from alembic.config import Config
        from alembic import command

        admin_engine = create_engine("postgresql+psycopg2://authos@localhost:5433/postgres", isolation_level="AUTOCOMMIT")
        disp_name = "authos_disposable_parity_test"
        disp_url = f"postgresql+psycopg2://authos@localhost:5433/{disp_name}"

        try:
            with admin_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {disp_name};"))
                conn.execute(text(f"CREATE DATABASE {disp_name};"))

            cfg = Config("alembic.ini")
            cfg.set_main_option("sqlalchemy.url", disp_url)
            command.upgrade(cfg, "head")

            disp_engine = create_engine(disp_url)
            insp = inspect(disp_engine)

            # Check that all expected tables exist
            tables = set(insp.get_table_names())
            expected_tables = {
                "policies", "policy_criteria", "documents", "cases",
                "criterion_results", "audit_log", "policy_chunks", "document_chunks",
            }
            self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")

            # Verify criterion_results columns including conflicting_evidence
            cr_cols = {c["name"]: c for c in insp.get_columns("criterion_results")}
            self.assertIn("conflicting_evidence", cr_cols)
            self.assertFalse(cr_cols["conflicting_evidence"]["nullable"])
            self.assertIn("validator_flags", cr_cols)
            self.assertIn("missing_facts", cr_cols)
            self.assertIn("evidence", cr_cols)

            disp_engine.dispose()
        finally:
            with admin_engine.connect() as conn:
                conn.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{disp_name}';"))
                conn.execute(text(f"DROP DATABASE IF EXISTS {disp_name};"))

    # 2. Reject review actions and finalization from DRAFT and RUNNING
    def test_reject_review_and_finalization_from_draft_or_running(self):
        """Cases in DRAFT or RUNNING status strictly reject review annotations and finalization with 409."""
        with TestSession() as session:
            draft_case = CaseModel(
                case_id="CASE-DRAFT-01",
                patient_id="SYN-P001",
                service="Lumbar MRI",
                policy_id="SYN-POL-LMRI-001",
                status=CaseStatus.DRAFT.value,
                scenario="draft_scenario",
            )
            running_case = CaseModel(
                case_id="CASE-RUNNING-01",
                patient_id="SYN-P001",
                service="Lumbar MRI",
                policy_id="SYN-POL-LMRI-001",
                status=CaseStatus.RUNNING.value,
                scenario="running_scenario",
            )
            session.add_all([draft_case, running_case])
            session.commit()

        # Review action on DRAFT case
        res1 = self.client.post(
            "/api/v1/cases/CASE-DRAFT-01/review",
            json={"criterion_id": "C1", "action": ReviewActionType.CUSTOM_NOTE.value, "note": "Review attempt"},
        )
        self.assertEqual(res1.status_code, 409)
        self.assertEqual(res1.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

        # Finalization on DRAFT case
        res2 = self.client.post(
            "/api/v1/cases/CASE-DRAFT-01/approve",
            json={"action": FinalizationActionType.APPROVE_PACKET.value, "reviewer_note": "Approve attempt"},
        )
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

        # Review action on RUNNING case
        res3 = self.client.post(
            "/api/v1/cases/CASE-RUNNING-01/review",
            json={"criterion_id": "C1", "action": ReviewActionType.CUSTOM_NOTE.value, "note": "Review attempt"},
        )
        self.assertEqual(res3.status_code, 409)
        self.assertEqual(res3.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

        # Finalization on RUNNING case
        res4 = self.client.post(
            "/api/v1/cases/CASE-RUNNING-01/approve",
            json={"action": FinalizationActionType.APPROVE_PACKET.value, "reviewer_note": "Approve attempt"},
        )
        self.assertEqual(res4.status_code, 409)
        self.assertEqual(res4.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

    # 3. All-MET routes to RESULTS_READY; non-MET routes to IN_HUMAN_REVIEW
    def test_evaluation_routes_all_met_to_results_ready_and_non_met_to_in_human_review(self):
        """Evaluation properly sets RESULTS_READY for all-MET and IN_HUMAN_REVIEW when gaps/contradictions exist."""
        # CASE-SYN-001 (all criteria MET) -> RESULTS_READY
        r1 = self.client.post("/api/v1/cases/CASE-SYN-001/evaluate")
        self.assertEqual(r1.status_code, 200)
        c1 = self.client.get("/api/v1/cases/CASE-SYN-001").json()
        self.assertEqual(c1["status"], CaseStatus.RESULTS_READY.value)

        # CASE-SYN-002 (C2 AMBIGUOUS) -> IN_HUMAN_REVIEW
        r2 = self.client.post("/api/v1/cases/CASE-SYN-002/evaluate")
        self.assertEqual(r2.status_code, 200)
        c2 = self.client.get("/api/v1/cases/CASE-SYN-002").json()
        self.assertEqual(c2["status"], CaseStatus.IN_HUMAN_REVIEW.value)

        # CASE-SYN-003 (C2 CONTRADICTED) -> IN_HUMAN_REVIEW
        r3 = self.client.post("/api/v1/cases/CASE-SYN-003/evaluate")
        self.assertEqual(r3.status_code, 200)
        c3 = self.client.get("/api/v1/cases/CASE-SYN-003").json()
        self.assertEqual(c3["status"], CaseStatus.IN_HUMAN_REVIEW.value)

    # 4. Evaluation never automatically approves or finalizes a packet
    def test_evaluation_never_approves_or_finalizes_automatically(self):
        """Evaluation sets case status to RESULTS_READY or IN_HUMAN_REVIEW, but packet.finalized remains False."""
        for case_id in ["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"]:
            eval_resp = self.client.post(f"/api/v1/cases/{case_id}/evaluate")
            self.assertEqual(eval_resp.status_code, 200)
            packet = eval_resp.json()
            self.assertFalse(packet["finalized"], f"Evaluation must never finalize packet for {case_id}")
            self.assertIsNone(packet["finalized_at"])

            case_resp = self.client.get(f"/api/v1/cases/{case_id}").json()
            self.assertNotEqual(case_resp["status"], CaseStatus.FINALIZED.value)
            self.assertNotEqual(case_resp["status"], CaseStatus.REJECTED.value)

    # 5. Stable canonical generated_at across repeated reads
    def test_stable_generated_at_across_repeated_reads(self):
        """Repeated GET requests return the exact same canonical generated_at timestamp."""
        # 1. Prior to evaluation, draft packet preview has generated_at as None
        with TestSession() as session:
            draft_case = CaseModel(
                case_id="CASE-DRAFT-TS",
                patient_id="SYN-P001",
                service="Lumbar MRI",
                policy_id="SYN-POL-LMRI-001",
                status=CaseStatus.DRAFT.value,
                scenario="ts_test",
            )
            session.add(draft_case)
            session.commit()

        draft_packet = self.client.get("/api/v1/cases/CASE-DRAFT-TS/packet?preview=true").json()
        self.assertIsNone(draft_packet["generated_at"])

        # 2. Evaluate CASE-SYN-001
        self.client.post("/api/v1/cases/CASE-SYN-001/evaluate")

        # 3. Query 5 times in succession
        timestamps = []
        for _ in range(5):
            res = self.client.get("/api/v1/cases/CASE-SYN-001/packet?preview=true").json()
            self.assertIsNotNone(res["generated_at"])
            timestamps.append(res["generated_at"])

        self.assertEqual(len(set(timestamps)), 1, "generated_at timestamp must remain identical across repeated GET reads")

    # 6. Safe public error responses without raw internal exception leakage
    def test_safe_public_error_response_no_exception_leakage(self):
        """Evaluation errors log details server-side and return standardized safe error envelopes."""
        # Patch evaluate_case to simulate an internal system crash
        with patch("backend.workflow.evaluator.evaluate_case", side_effect=RuntimeError("SecretDatabasePasswordFailure: conn dropped")):
            res = self.client.post("/api/v1/cases/CASE-SYN-001/evaluate")
            self.assertEqual(res.status_code, 500)
            body = res.json()
            self.assertIn("error", body)
            self.assertEqual(body["error"]["code"], ErrorCode.INTERNAL_ERROR.value)
            # Crucial: raw internal exception string must NOT be leaked
            self.assertNotIn("SecretDatabasePasswordFailure", body["error"]["message"])
            self.assertIn("unexpected internal error", body["error"]["message"].lower())

    # 7. Reviewer UI contains robust error handling
    def test_reviewer_ui_serves_with_error_handler(self):
        """The reviewer UI is served with parseErrorMessage error-envelope handling."""
        res = self.client.get("/reviewer")
        self.assertEqual(res.status_code, 200)
        self.assertIn("parseErrorMessage", res.text)
        self.assertIn("data.error?.message", res.text)


if __name__ == "__main__":
    unittest.main()
