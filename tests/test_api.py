"""Contract and integration tests for FastAPI /api/v1 endpoints."""
import unittest
from fastapi.testclient import TestClient

from backend.main import create_app
from contracts.schemas import (
    CriterionStatus,
    ErrorCode,
    FinalizationActionType,
    ReviewActionType,
)
from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.auth.security import create_access_token
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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB_URL = "postgresql+psycopg2://authos@localhost:5433/authos_test"
test_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


class ApiContractTests(unittest.TestCase):
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
            session.commit()

        self.repo = PostgresCaseRepository(session_factory=TestSession)
        self.app = create_app()
        self.app.dependency_overrides[get_repository] = lambda: self.repo
        self.client = TestClient(self.app)
        dev_reviewer = AuthenticatedUser(
            sub="REV-001",
            name="Dr. Sarah Chen, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["*"],
        )
        token = create_access_token(dev_reviewer)
        self.client.headers["Authorization"] = f"Bearer {token}"

    def test_health_check(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("version"), "v1")

    def test_list_cases_returns_three_synthetic_cases(self):
        response = self.client.get("/api/v1/cases")
        self.assertEqual(response.status_code, 200)
        cases = response.json()
        self.assertEqual(len(cases), 3)
        case_ids = [c["case_id"] for c in cases]
        self.assertIn("CASE-SYN-001", case_ids)
        self.assertIn("CASE-SYN-002", case_ids)
        self.assertIn("CASE-SYN-003", case_ids)

    def test_get_case_detail_success(self):
        response = self.client.get("/api/v1/cases/CASE-SYN-001")
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(case["case_id"], "CASE-SYN-001")
        self.assertEqual(case["patient_id"], "SYN-P001")
        self.assertEqual(case["service"], "Lumbar MRI")

    def test_get_case_detail_not_found(self):
        response = self.client.get("/api/v1/cases/CASE-UNKNOWN")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["code"], ErrorCode.CASE_NOT_FOUND.value)

    def test_get_case_results_success(self):
        response = self.client.get("/api/v1/cases/CASE-SYN-001/results")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["case_id"], "CASE-SYN-001")
        self.assertEqual(len(data["criteria_results"]), 3)
        self.assertTrue(all(r["status"] == CriterionStatus.MET.value for r in data["criteria_results"]))

    def test_get_case_results_ambiguous_scenario(self):
        response = self.client.get("/api/v1/cases/CASE-SYN-002/results")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        c2 = next(r for r in data["criteria_results"] if r["criterion_id"] == "C2")
        self.assertEqual(c2["status"], CriterionStatus.AMBIGUOUS.value)
        self.assertFalse(c2["verified"])
        self.assertIn("duration_weeks", c2["missing_facts"])
        self.assertEqual(len(c2["retry_log"]), 2)

    def test_get_case_results_contradicted_scenario(self):
        response = self.client.get("/api/v1/cases/CASE-SYN-003/results")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        c2 = next(r for r in data["criteria_results"] if r["criterion_id"] == "C2")
        self.assertEqual(c2["status"], CriterionStatus.CONTRADICTED.value)
        self.assertFalse(c2["verified"])
        self.assertIn("PATIENT_DECLINED_TREATMENT", c2["validator_flags"])

    def test_post_review_action_success(self):
        payload = {
            "criterion_id": "C2",
            "action": ReviewActionType.REQUEST_INFORMATION.value,
            "note": "Please request therapy attendance records from provider.",
        }
        response = self.client.post("/api/v1/cases/CASE-SYN-002/review", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["case_id"], "CASE-SYN-002")
        self.assertEqual(data["criterion_id"], "C2")
        self.assertEqual(data["action"], ReviewActionType.REQUEST_INFORMATION.value)

    def test_post_review_action_validation_error(self):
        # Invalid action enum
        payload = {
            "criterion_id": "C2",
            "action": "unsupported_action",
            "note": "Some note",
        }
        response = self.client.post("/api/v1/cases/CASE-SYN-002/review", json=payload)
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["code"], ErrorCode.VALIDATION_ERROR.value)

    def test_approve_packet_and_retrieve_packet(self):
        # Initial retrieval of unfinalized packet without preview flag returns 409
        response_before = self.client.get("/api/v1/cases/CASE-SYN-001/packet")
        self.assertEqual(response_before.status_code, 409)
        self.assertEqual(response_before.json()["error"]["code"], ErrorCode.PACKET_NOT_FINALIZED.value)

        # Retrieval with preview=true is allowed for inspection
        preview_response = self.client.get("/api/v1/cases/CASE-SYN-001/packet?preview=true")
        self.assertEqual(preview_response.status_code, 200)
        self.assertFalse(preview_response.json()["finalized"])

        # Approve packet
        approve_payload = {
            "action": FinalizationActionType.APPROVE_PACKET.value,
            "reviewer_note": "Reviewed all criteria and supporting verified evidence.",
        }
        approve_response = self.client.post("/api/v1/cases/CASE-SYN-001/approve", json=approve_payload)
        self.assertEqual(approve_response.status_code, 200)
        finalized_packet = approve_response.json()
        self.assertTrue(finalized_packet["finalized"])
        self.assertIsNotNone(finalized_packet["finalized_at"])

        # Subsequent GET packet returns finalized packet
        response_after = self.client.get("/api/v1/cases/CASE-SYN-001/packet")
        self.assertEqual(response_after.status_code, 200)
        self.assertTrue(response_after.json()["finalized"])

    def test_post_review_action_unknown_criterion_fails(self):
        payload = {
            "criterion_id": "C999",
            "action": ReviewActionType.REQUEST_INFORMATION.value,
            "note": "Unknown criterion.",
        }
        response = self.client.post("/api/v1/cases/CASE-SYN-002/review", json=payload)
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"]["code"], ErrorCode.VALIDATION_ERROR.value)

    def test_post_review_action_on_finalized_case_fails(self):
        # Finalize CASE-SYN-001 first
        self.client.post(
            "/api/v1/cases/CASE-SYN-001/approve",
            json={"action": FinalizationActionType.APPROVE_PACKET.value, "reviewer_note": "Approved."},
        )
        # Attempt to add review action to now-finalized case
        response = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            json={
                "criterion_id": "C1",
                "action": ReviewActionType.REQUEST_INFORMATION.value,
                "note": "Late note.",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

    def test_repeated_approval_fails(self):
        approve_payload = {
            "action": FinalizationActionType.APPROVE_PACKET.value,
            "reviewer_note": "Initial approval.",
        }
        res1 = self.client.post("/api/v1/cases/CASE-SYN-001/approve", json=approve_payload)
        self.assertEqual(res1.status_code, 200)

        # Second approval attempt should return 409 INVALID_STATE_TRANSITION
        res2 = self.client.post("/api/v1/cases/CASE-SYN-001/approve", json=approve_payload)
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

    def test_reject_packet_does_not_finalize(self):
        reject_payload = {
            "action": FinalizationActionType.REJECT_PACKET.value,
            "reviewer_note": "Documentation completely inadequate.",
        }
        res = self.client.post("/api/v1/cases/CASE-SYN-003/approve", json=reject_payload)
        self.assertEqual(res.status_code, 200)
        packet = res.json()
        self.assertFalse(packet["finalized"])
        self.assertIn("REJECTED", packet["reviewer_note"])

        # Case status should now be REJECTED
        case_res = self.client.get("/api/v1/cases/CASE-SYN-003")
        self.assertEqual(case_res.json()["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
