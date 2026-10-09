import json
import unittest
from pathlib import Path
from backend.authos_core.verifier import verify_claim, render_review_packet

ROOT = Path(__file__).resolve().parents[1]
PATIENTS = json.loads((ROOT / "data/synthetic/patients.json").read_text())

class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.docs = PATIENTS[0]["documents"]

    def test_accepts_exact_quote_from_correct_patient(self):
        result = verify_claim({"claim_id":"CL-1", "source_id":"SYN-P001-PT-02", "quote":"Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms."}, patient_id="SYN-P001", source_documents=self.docs)
        self.assertTrue(result.accepted)
        self.assertEqual(result.reasons, [])

    def test_rejects_non_verbatim_quote(self):
        result = verify_claim({"claim_id":"CL-2", "source_id":"SYN-P001-PT-02", "quote":"Patient completed eight weeks of therapy."}, patient_id="SYN-P001", source_documents=self.docs)
        self.assertFalse(result.accepted)
        self.assertIn("QUOTE_NOT_VERBATIM", result.reasons)

    def test_rejects_wrong_patient_source(self):
        result = verify_claim({"claim_id":"CL-3", "source_id":"SYN-P001-PT-02", "quote":"Patient completed supervised physical therapy from July 1 through August 20, 2026, with persistent symptoms."}, patient_id="SYN-P002", source_documents=self.docs)
        self.assertFalse(result.accepted)
        self.assertIn("PATIENT_MISMATCH", result.reasons)

    def test_rejects_missing_source(self):
        result = verify_claim({"claim_id":"CL-4", "source_id":"UNKNOWN", "quote":"some quote"}, patient_id="SYN-P001", source_documents=self.docs)
        self.assertFalse(result.accepted)
        self.assertIn("SOURCE_NOT_FOUND", result.reasons)

    def test_packet_is_template_rendered_and_not_finalized(self):
        packet = render_review_packet(case_id="CASE-1", patient_id="SYN-P001", criterion_results=[{"criterion_id":"C2", "criterion":"Treatment history", "status":"AMBIGUOUS", "verified_evidence":[], "reason":"Duration not established"}])
        self.assertEqual(packet["packet_type"], "SYNTHETIC_DEMO_REVIEW_PACKET")
        self.assertFalse(packet["finalized"])
        self.assertTrue(packet["criteria"][0]["review_required"])

    def test_rejects_empty_or_whitespace_quote(self):
        result = verify_claim(
            {"claim_id": "CL-5", "source_id": "SYN-P001-PT-02", "quote": "   "},
            patient_id="SYN-P001",
            source_documents=self.docs,
        )
        self.assertFalse(result.accepted)
        self.assertIn("QUOTE_MISSING", result.reasons)

    def test_rejects_subtle_date_fabrication_in_quote(self):
        # Only one character difference ("July 2" instead of "July 1")
        subtle_fake = "Patient completed supervised physical therapy from July 2 through August 20, 2026, with persistent symptoms."
        result = verify_claim(
            {"claim_id": "CL-6", "source_id": "SYN-P001-PT-02", "quote": subtle_fake},
            patient_id="SYN-P001",
            source_documents=self.docs,
        )
        self.assertFalse(result.accepted)
        self.assertIn("QUOTE_NOT_VERBATIM", result.reasons)


if __name__ == "__main__":
    unittest.main()
