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


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)

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


if __name__ == "__main__":
    unittest.main()
