"""Validation tests for synthetic mock response fixtures against Pydantic schemas."""
import json
import unittest
from pathlib import Path

from contracts.schemas import (
    Case,
    CaseResultsResponse,
    CriterionStatus,
    ReviewPacket,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "contracts" / "mock_response.json"


class FixturesContractTests(unittest.TestCase):
    def setUp(self):
        self.raw_data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))

    def test_fixture_cases_schema_compliance(self):
        cases_data = self.raw_data.get("cases", [])
        self.assertEqual(len(cases_data), 3)
        cases = [Case.model_validate(c) for c in cases_data]
        self.assertEqual(cases[0].case_id, "CASE-SYN-001")
        self.assertEqual(cases[1].case_id, "CASE-SYN-002")
        self.assertEqual(cases[2].case_id, "CASE-SYN-003")

    def test_fixture_case_results_schema_compliance(self):
        results_by_case = self.raw_data.get("results_by_case", {})
        self.assertIn("CASE-SYN-001", results_by_case)
        self.assertIn("CASE-SYN-002", results_by_case)
        self.assertIn("CASE-SYN-003", results_by_case)

        # Validate Case 1: Happy path
        c1 = CaseResultsResponse.model_validate(results_by_case["CASE-SYN-001"])
        self.assertEqual(c1.scenario, "sufficient_evidence")
        self.assertTrue(all(r.status == CriterionStatus.MET and r.verified for r in c1.criteria_results))

        # Validate Case 2: Requires review (Ambiguous)
        c2 = CaseResultsResponse.model_validate(results_by_case["CASE-SYN-002"])
        self.assertEqual(c2.scenario, "evidence_requires_review")
        c2_criteria = {r.criterion_id: r for r in c2.criteria_results}
        self.assertEqual(c2_criteria["C2"].status, CriterionStatus.AMBIGUOUS)
        self.assertFalse(c2_criteria["C2"].verified)
        self.assertGreater(len(c2_criteria["C2"].missing_facts), 0)
        self.assertEqual(len(c2_criteria["C2"].retry_log), 2)  # exercises corrective retry

        # Validate Case 3: Contradictory evidence
        c3 = CaseResultsResponse.model_validate(results_by_case["CASE-SYN-003"])
        self.assertEqual(c3.scenario, "contradictory_evidence")
        c3_criteria = {r.criterion_id: r for r in c3.criteria_results}
        self.assertEqual(c3_criteria["C2"].status, CriterionStatus.CONTRADICTED)
        self.assertFalse(c3_criteria["C2"].verified)
        self.assertIn("PATIENT_DECLINED_TREATMENT", c3_criteria["C2"].validator_flags)

    def test_fixture_packet_schema_compliance(self):
        packets_by_case = self.raw_data.get("packets_by_case", {})
        self.assertIn("CASE-SYN-001", packets_by_case)
        packet = ReviewPacket.model_validate(packets_by_case["CASE-SYN-001"])
        self.assertEqual(packet.packet_type, "SYNTHETIC_DEMO_REVIEW_PACKET")
        self.assertFalse(packet.finalized)
        self.assertEqual(len(packet.criteria), 3)


if __name__ == "__main__":
    unittest.main()
