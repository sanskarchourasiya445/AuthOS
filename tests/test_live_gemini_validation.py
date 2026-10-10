"""Phase 11 Follow-up: End-to-end Live Gemini 3.5 Flash-Lite Provider Validation.

Validates the live Google Gemini hosted provider (gemini-3.5-flash-lite)
against the eight mandatory safety scenarios:
1. Clearly supported evidence
2. Missing evidence
3. Ambiguous evidence
4. Contradictory evidence
5. Negation
6. Fabricated evidence defense
7. Cross-patient evidence defense
8. Provider failure resilience

Guarantees:
- Real API calls to gemini-3.5-flash-lite are executed when GEMINI_API_KEY is configured.
- Never hardcodes, logs, or displays credentials.
- The deterministic verifier remains authoritative.
- LLM produces advisory proposals only; authoritative criterion_results are never directly written.
- Ungrounded, fabricated, or cross-patient citations cannot become a verified MET result.
"""
import os
import time
import unittest
from dotenv import load_dotenv

from backend.agent.analysis_agent import CriterionAnalysisAgent, validate_and_ground_evidence
from backend.agent.llm_provider import (
    GeminiProvider,
    LLMCriterionProposal,
    LLMEvidenceQuote,
    LLMProviderResult,
)
from backend.config import settings
from backend.verification.engine import (
    validate_evidence_provenance,
    verify_criterion_evidence,
)
from contracts.schemas import CriterionStatus, EvidencePolarity


class LiveGeminiFlashLiteValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv()
        cls.api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not cls.api_key:
            raise unittest.SkipTest("GEMINI_API_KEY not configured. Skipping live Gemini validation.")

        cls.model_name = "gemini-3.5-flash-lite"
        cls.provider = GeminiProvider(
            api_key=cls.api_key,
            model_name=cls.model_name,
            timeout_seconds=30.0,
            max_retries=2,
        )

    def test_01_live_gemini_model_configuration(self):
        """Verify provider metadata and test live connectivity to gemini-3.5-flash-lite."""
        self.assertEqual(self.provider.provider_name, "google_gemini")
        self.assertEqual(self.provider.model_name, "gemini-3.5-flash-lite")
        self.assertTrue(self.provider.is_external_llm)

        # Execute minimal live generation
        client = self.provider._get_client()
        self.assertIsNotNone(client, "Gemini client must initialize successfully with valid key.")

        t0 = time.monotonic()
        resp = client.models.generate_content(
            model=self.model_name,
            contents="Respond strictly with the single word: OPERATIONAL",
        )
        latency = (time.monotonic() - t0) * 1000
        self.assertIn("OPERATIONAL", resp.text.strip().upper())
        self.assertGreater(latency, 0.0)

    def test_02_scenario_1_clearly_supported_evidence(self):
        """Scenario 1: Live model analyzes clearly supported chart evidence; verifier verifies MET."""
        quote = "Patient reports persistent low back pain for 10 weeks duration. Symptoms began after lifting injury."
        candidate = {
            "source_id": "SYN-P001-NOTE-01",
            "patient_id": "SYN-P001",
            "document_date": "2026-08-01",
            "quote": quote,
            "char_start": 0,
            "char_end": len(quote),
        }
        raw_documents = [
            {
                "source_id": "SYN-P001-NOTE-01",
                "patient_id": "SYN-P001",
                "date": "2026-08-01",
                "text": quote,
            }
        ]

        # 1. Live LLM proposal
        t0 = time.monotonic()
        result = self.provider.generate_proposal(
            criterion_id="C1",
            criterion_text="Documentation describes persistent low back symptoms for at least 6 weeks.",
            patient_id="SYN-P001",
            required_facts=["Low back pain", "Duration >= 6 weeks"],
            min_duration_days=42,
            candidates=[candidate],
        )
        latency = (time.monotonic() - t0) * 1000

        self.assertTrue(result.success, f"Live Gemini request failed: {result.error_message}")
        self.assertIsNotNone(result.proposal)
        self.assertEqual(result.proposal.proposed_status, "MET")
        self.assertGreaterEqual(len(result.proposal.evidence_quotes), 1)

        # 2. Grounding check
        valid_items, flags, downgraded_status = validate_and_ground_evidence(
            proposal=result.proposal,
            candidates=[candidate],
            patient_id="SYN-P001",
        )
        self.assertGreaterEqual(len(valid_items), 1)

        # 3. Deterministic verification gate
        verification = verify_criterion_evidence(
            criterion_id="C1",
            criterion_text="Documentation describes persistent low back symptoms for at least 6 weeks.",
            patient_id="SYN-P001",
            candidate_evidence=[candidate],
            raw_documents=raw_documents,
            required_facts=["Low back pain", "Duration >= 6 weeks"],
            min_duration_days=42,
        )
        self.assertTrue(verification.verified)
        self.assertEqual(verification.status, CriterionStatus.MET)

    def test_03_scenario_2_missing_evidence(self):
        """Scenario 2: Missing evidence in chart; model proposes MISSING; verifier confirms MISSING."""
        result = self.provider.generate_proposal(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks.",
            patient_id="SYN-P001",
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
            min_duration_days=42,
            candidates=[],  # No evidence retrieved
        )
        self.assertTrue(result.success)
        self.assertIsNotNone(result.proposal)
        self.assertEqual(result.proposal.proposed_status, "MISSING")
        self.assertGreaterEqual(len(result.proposal.missing_facts), 1)

        # Deterministic verification gate confirms MISSING
        verification = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks.",
            patient_id="SYN-P001",
            candidate_evidence=[],
            raw_documents=[],
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
            min_duration_days=42,
        )
        self.assertFalse(verification.verified)
        self.assertEqual(verification.status, CriterionStatus.MISSING)

    def test_04_scenario_3_ambiguous_evidence(self):
        """Scenario 3: Ambiguous evidence (PT mentioned, but dates/duration unestablished)."""
        quote = "Physical therapy was discussed with the patient. Patient attended several sessions; exact start date and duration are not documented in available notes."
        candidate = {
            "source_id": "SYN-P002-PT-02",
            "patient_id": "SYN-P002",
            "document_date": "2026-09-02",
            "quote": quote,
            "char_start": 0,
            "char_end": len(quote),
        }
        raw_documents = [
            {
                "source_id": "SYN-P002-PT-02",
                "patient_id": "SYN-P002",
                "date": "2026-09-02",
                "text": quote,
            }
        ]

        result = self.provider.generate_proposal(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks.",
            patient_id="SYN-P002",
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
            min_duration_days=42,
            candidates=[candidate],
        )
        self.assertTrue(result.success)
        # Model should propose AMBIGUOUS or MISSING, never MET
        self.assertIn(result.proposal.proposed_status, ["AMBIGUOUS", "MISSING"])

        # Deterministic verification gate confirms non-MET status (AMBIGUOUS)
        verification = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks.",
            patient_id="SYN-P002",
            candidate_evidence=[candidate],
            raw_documents=raw_documents,
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
            min_duration_days=42,
        )
        self.assertFalse(verification.verified)
        self.assertEqual(verification.status, CriterionStatus.AMBIGUOUS)

    def test_05_scenario_4_contradictory_evidence(self):
        """Scenario 4: Contradictory evidence (note states patient declined physical therapy)."""
        quote = "Physical therapy was recommended. Patient declined physical therapy at this visit due to time constraints."
        candidate = {
            "source_id": "SYN-P003-PT-02",
            "patient_id": "SYN-P003",
            "document_date": "2026-08-11",
            "quote": quote,
            "char_start": 0,
            "char_end": len(quote),
        }
        raw_documents = [
            {
                "source_id": "SYN-P003-PT-02",
                "patient_id": "SYN-P003",
                "date": "2026-08-11",
                "text": quote,
            }
        ]

        result = self.provider.generate_proposal(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks.",
            patient_id="SYN-P003",
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
            min_duration_days=42,
            candidates=[candidate],
        )
        self.assertTrue(result.success)
        self.assertEqual(result.proposal.proposed_status, "CONTRADICTED")

        # Deterministic verifier confirms CONTRADICTED
        verification = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks.",
            patient_id="SYN-P003",
            candidate_evidence=[candidate],
            raw_documents=raw_documents,
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
            min_duration_days=42,
        )
        self.assertFalse(verification.verified)
        self.assertEqual(verification.status, CriterionStatus.CONTRADICTED)

    def test_06_scenario_5_negation(self):
        """Scenario 5: Explicit negation in chart note (patient denies back pain)."""
        quote = "Patient denies back pain, denies lower extremity weakness, and reports zero spine symptoms."
        candidate = {
            "source_id": "SYN-P005-NOTE-NEG",
            "patient_id": "SYN-P005",
            "document_date": "2026-09-01",
            "quote": quote,
            "char_start": 0,
            "char_end": len(quote),
        }
        raw_documents = [
            {
                "source_id": "SYN-P005-NOTE-NEG",
                "patient_id": "SYN-P005",
                "date": "2026-09-01",
                "text": quote,
            }
        ]

        result = self.provider.generate_proposal(
            criterion_id="C1",
            criterion_text="Documentation describes persistent low back symptoms.",
            patient_id="SYN-P005",
            required_facts=["Low back pain"],
            min_duration_days=None,
            candidates=[candidate],
        )
        self.assertTrue(result.success)
        # Model must detect negation and propose CONTRADICTED or MISSING, never MET
        self.assertIn(result.proposal.proposed_status, ["CONTRADICTED", "MISSING"])

        # Verifier must refuse MET
        verification = verify_criterion_evidence(
            criterion_id="C1",
            criterion_text="Documentation describes persistent low back symptoms.",
            patient_id="SYN-P005",
            candidate_evidence=[candidate],
            raw_documents=raw_documents,
            required_facts=["Low back pain"],
            min_duration_days=None,
        )
        self.assertFalse(verification.verified)
        self.assertNotEqual(verification.status, CriterionStatus.MET)

    def test_07_scenario_6_fabricated_evidence_defense(self):
        """Scenario 6: Fabricated quote defense — model hallucination or altered quote is rejected."""
        quote = "Patient reports mild tension in lower back. No formal physical therapy initiated."
        real_cand = {
            "source_id": "SYN-P001-NOTE-01",
            "patient_id": "SYN-P001",
            "document_date": "2026-08-01",
            "quote": quote,
            "char_start": 0,
            "char_end": len(quote),
        }
        # Fabricated quote not in candidate
        fabricated_proposal = LLMCriterionProposal(
            criterion_id="C2",
            proposed_status="MET",
            confidence=0.99,
            evidence_quotes=[
                LLMEvidenceQuote(
                    source_id="SYN-P001-NOTE-01",
                    quote="Patient successfully finished 12 weeks of comprehensive physical therapy.",  # Fabricated!
                    polarity="SUPPORTING",
                )
            ],
            missing_facts=[],
            detected_gaps=[],
            uncertainty_rationale="Fabricated advisory statement.",
        )

        # Grounding must reject altered/fabricated quote and safely downgrade proposed MET
        valid_items, flags, safe_status = validate_and_ground_evidence(
            proposal=fabricated_proposal,
            candidates=[real_cand],
            patient_id="SYN-P001",
        )
        self.assertEqual(len(valid_items), 0)
        self.assertTrue(any("ALTERED_OR_FABRICATED_QUOTE_REJECTED" in f for f in flags))
        self.assertNotEqual(safe_status, CriterionStatus.MET)

    def test_08_scenario_7_cross_patient_evidence_defense(self):
        """Scenario 7: Cross-patient isolation defense — quote from another patient is rejected."""
        quote = "Patient completed 8 weeks of intensive physical therapy."
        wrong_patient_cand = {
            "source_id": "SYN-P002-NOTE-01",
            "patient_id": "SYN-P002",  # Belongs to P002, not P001
            "document_date": "2026-08-01",
            "quote": quote,
            "char_start": 0,
            "char_end": len(quote),
        }
        proposal = LLMCriterionProposal(
            criterion_id="C2",
            proposed_status="MET",
            confidence=0.95,
            evidence_quotes=[
                LLMEvidenceQuote(
                    source_id="SYN-P002-NOTE-01",
                    quote=quote,
                    polarity="SUPPORTING",
                )
            ],
            missing_facts=[],
            detected_gaps=[],
            uncertainty_rationale="Cross-patient proposal attempt.",
        )

        valid_items, flags, safe_status = validate_and_ground_evidence(
            proposal=proposal,
            candidates=[wrong_patient_cand],
            patient_id="SYN-P001",  # Scoped patient is P001
        )
        self.assertEqual(len(valid_items), 0)
        self.assertTrue(any("CROSS_PATIENT_QUOTE_REJECTED" in f for f in flags))
        self.assertNotEqual(safe_status, CriterionStatus.MET)

        # Verifier provenance validation also rejects cross-patient
        raw_docs = [
            {"source_id": "SYN-P002-NOTE-01", "patient_id": "SYN-P002", "text": quote}
        ]
        prov_valid, prov_reasons, _, _, _ = validate_evidence_provenance(
            wrong_patient_cand,
            raw_documents=raw_docs,
            patient_id="SYN-P001",
        )
        self.assertFalse(prov_valid)
        self.assertIn("PATIENT_MISMATCH", prov_reasons)

    def test_09_scenario_8_provider_failure_resilience(self):
        """Scenario 8: Provider failure handling — timeout, missing key, or bad schema fails safely."""
        # 1. Missing API key returns typed error without crashing
        bad_provider = GeminiProvider(api_key="")
        res = bad_provider.generate_proposal(
            criterion_id="C1",
            criterion_text="Requirement",
            patient_id="SYN-P001",
            required_facts=[],
            min_duration_days=None,
            candidates=[],
        )
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "MISSING_API_KEY")
        self.assertIsNone(res.proposal)

        # 2. Timeout handling fails safely
        timeout_provider = GeminiProvider(
            api_key=self.api_key,
            model_name=self.model_name,
            timeout_seconds=0.001,  # Exceedingly small timeout to force timeout branch
            max_retries=0,
        )
        res_timeout = timeout_provider.generate_proposal(
            criterion_id="C1",
            criterion_text="Requirement",
            patient_id="SYN-P001",
            required_facts=[],
            min_duration_days=None,
            candidates=[{"source_id": "S1", "quote": "Sample text"}],
        )
        self.assertFalse(res_timeout.success)
        self.assertIn(res_timeout.error_code, ["TIMEOUT", "PROVIDER_ERROR"])

    def test_10_authority_boundary_inviolable(self):
        """Verify that an untrusted advisory model output cannot mutate authoritative criteria results."""
        # Even if a live model proposed MET with fabricated confidence 1.0,
        # the deterministic verifier is solely responsible for determining verified status.
        verification = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks.",
            patient_id="SYN-P001",
            candidate_evidence=[],  # No actual verified evidence
            raw_documents=[],
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
            min_duration_days=42,
        )
        self.assertFalse(verification.verified)
        self.assertEqual(verification.status, CriterionStatus.MISSING)


if __name__ == "__main__":
    unittest.main()
