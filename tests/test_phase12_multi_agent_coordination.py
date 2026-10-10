"""Targeted regression and safety suite for AuthOS Phase 12 Multi-Agent Improvements.

Tests:
1. Full-chart vs degraded-fixture evaluation population separation.
2. Ground-truth consistency across full-chart criteria.
3. Candidate evidence accumulation across iterative retrieval rounds.
4. Deterministic verifier feedback enrichment into agent retry state.
5. Short-circuiting of retries upon confirmed clinical contradiction/refusal.
6. Fail-closed downgrade of unsupported MET proposals.
7. Rejection of cross-patient citations and patient boundary guards.
8. Detection of explicit clinical symptom negation.
9. Missing credentials fail-safe (explicit typed error, zero simulated cloud responses).
10. Socket-level HTTP timeout configuration on Gemini client.
11. Strict separation of advisory proposals from authoritative verification results.
12. Offline benchmark runner execution with 100% determinism.
"""
from datetime import datetime, timezone
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.agent.analysis_agent import CriterionAnalysisAgent, validate_and_ground_evidence
from backend.agent.llm_provider import (
    GeminiProvider,
    LLMCriterionProposal,
    LLMEvidenceQuote,
    LLMProviderResult,
)
from backend.agent.orchestrator import AgentOrchestrator
from backend.agent.retrieval_agent import EvidenceRetrievalAgent
from backend.db.models import AgentProposalModel, CaseModel, CriterionResultModel, DocumentModel
from backend.db.seed import seed_synthetic_data
from backend.db.session import SessionLocal
from backend.evaluation.agent_eval import (
    run_comparative_agent_evaluation,
    run_full_chart_adjudication_benchmark,
    run_verifier_fixture_benchmark,
    seed_evaluation_environment,
)
from backend.evaluation.dataset import (
    FullChartEvalCase,
    VerificationEvalCase,
    load_default_evaluation_dataset,
)
from backend.verification.engine import detect_evidence_polarity, verify_criterion_evidence
from contracts.schemas import CriterionStatus, EvidenceItem, EvidencePolarity


class TestPhase12EvaluationAndCoordination(unittest.TestCase):
    """Test suite verifying Phase 12 evaluation architecture and coordination enhancements."""

    @classmethod
    def setUpClass(cls):
        with SessionLocal() as session:
            seed_evaluation_environment(session)

    def test_full_chart_vs_fixture_population_separation(self):
        """Verify that fixture benchmark and full-chart benchmark have distinct, non-conflated cases."""
        dataset = load_default_evaluation_dataset()
        self.assertEqual(len(dataset.verification_cases), 34)
        self.assertEqual(len(dataset.full_chart_cases), 18)

        # Fixture cases must have explicitly supplied candidate_evidence
        for c in dataset.verification_cases:
            self.assertIsInstance(c, VerificationEvalCase)
            self.assertIsInstance(c.candidate_evidence, list)

        # Full-chart cases evaluate end-to-end chart retrieval without hardcoded candidate fixtures
        for c in dataset.full_chart_cases:
            self.assertIsInstance(c, FullChartEvalCase)
            self.assertIn(c.patient_id, {"SYN-P001", "SYN-P002", "SYN-P003", "SYN-P004", "SYN-P005", "SYN-P006"})

    def test_full_chart_expected_status_soundness(self):
        """Verify that full-chart expected statuses strictly correspond to complete patient records."""
        dataset = load_default_evaluation_dataset()
        cases_by_id = {c.case_id: c for c in dataset.full_chart_cases}

        # SYN-P001 has 10 weeks pain, 50 days PT, and MRI order -> all MET
        self.assertEqual(cases_by_id["FC-01-P001-C1"].expected_status, CriterionStatus.MET)
        self.assertEqual(cases_by_id["FC-02-P001-C2"].expected_status, CriterionStatus.MET)
        self.assertEqual(cases_by_id["FC-03-P001-C3"].expected_status, CriterionStatus.MET)

        # SYN-P002 has PT discussed without dates -> C2 is AMBIGUOUS
        self.assertEqual(cases_by_id["FC-04-P002-C1"].expected_status, CriterionStatus.MET)
        self.assertEqual(cases_by_id["FC-05-P002-C2"].expected_status, CriterionStatus.AMBIGUOUS)
        self.assertEqual(cases_by_id["FC-06-P002-C3"].expected_status, CriterionStatus.MET)

        # SYN-P003 declined PT -> C2 is CONTRADICTED
        self.assertEqual(cases_by_id["FC-07-P003-C1"].expected_status, CriterionStatus.MET)
        self.assertEqual(cases_by_id["FC-08-P003-C2"].expected_status, CriterionStatus.CONTRADICTED)
        self.assertEqual(cases_by_id["FC-09-P003-C3"].expected_status, CriterionStatus.MET)

        # Negative controls (P004, P005, P006) -> all MISSING
        for pid in ("P004", "P005", "P006"):
            for cid in ("C1", "C2", "C3"):
                case_key = f"FC-{[k for k in cases_by_id if pid in k and cid in k][0].split('-')[1]}-{pid}-{cid}"
                match = next(c for c in dataset.full_chart_cases if c.patient_id == f"SYN-{pid}" and c.criterion_id == cid)
                self.assertEqual(match.expected_status, CriterionStatus.MISSING)

    def test_candidate_accumulation_across_corrective_rounds(self):
        """Verify that iterative retrieval rounds accumulate candidates rather than discarding prior context."""
        with SessionLocal() as session:
            orchestrator = AgentOrchestrator(max_retries=2)
            raw_docs = session.query(DocumentModel).filter_by(patient_id="SYN-P002").all()
            raw_doc_dicts = [{"source_id": d.source_id, "patient_id": d.patient_id, "date": d.doc_date, "text": d.text} for d in raw_docs]

            compiled = orchestrator.build_graph(session, raw_doc_dicts)

            # Start with criterion C2 for SYN-P002 (ambiguous PT)
            initial_state = {
                "case_id": "CASE-SYN-002",
                "patient_id": "SYN-P002",
                "policy_id": "SYN-POL-LMRI-001",
                "run_id": "TEST-ACCUM-001",
                "criteria": [{
                    "criterion_id": "C2",
                    "criterion_text": "Conservative treatment history is documented for at least six weeks",
                    "evidence_expectation": None,
                    "required_facts": ["Supervised physical therapy", "Duration >= 6 weeks"],
                    "min_duration_days": 42,
                    "query": "Conservative treatment",
                    "retrieval_round": 1,
                    "candidates": [],
                    "proposal": None,
                    "verification_result": None,
                    "is_verified": False,
                    "missing_facts": [],
                    "detected_gaps": [],
                    "flags": [],
                    "status": "PENDING",
                }],
                "current_index": 0,
                "max_retries": 2,
                "time_budget_sec": 10.0,
                "start_time_monotonic": time.monotonic(),
                "total_retries": 0,
                "steps_log": [],
                "global_flags": [],
                "workflow_status": "RUNNING",
                "error_message": None,
            }

            final_state = compiled.invoke(initial_state)
            crit = final_state["criteria"][0]
            sources = {c.get("source_id") for c in crit["candidates"]}

            # Verify that round 2 executed and accumulated both PT-02 and ORDER-03
            self.assertEqual(crit["retrieval_round"], 2)
            self.assertIn("SYN-P002-PT-02", sources)
            self.assertIn("SYN-P002-ORDER-03", sources)

    def test_verifier_missing_facts_feedback_enrichment(self):
        """Verify that deterministic verifier flags enrich missing_facts for subsequent retrieval query reformulation."""
        with SessionLocal() as session:
            orchestrator = AgentOrchestrator(max_retries=2)
            raw_docs = session.query(DocumentModel).filter_by(patient_id="SYN-P002").all()
            raw_doc_dicts = [{"source_id": d.source_id, "patient_id": d.patient_id, "date": d.doc_date, "text": d.text} for d in raw_docs]

            compiled = orchestrator.build_graph(session, raw_doc_dicts)

            # Ambiguous PT case lacking duration
            initial_state = {
                "case_id": "CASE-SYN-002",
                "patient_id": "SYN-P002",
                "policy_id": "SYN-POL-LMRI-001",
                "run_id": "TEST-ENRICH-001",
                "criteria": [{
                    "criterion_id": "C2",
                    "criterion_text": "Conservative treatment history is documented for at least six weeks",
                    "evidence_expectation": None,
                    "required_facts": ["Supervised physical therapy", "Duration >= 6 weeks"],
                    "min_duration_days": 42,
                    "query": "Conservative treatment",
                    "retrieval_round": 1,
                    "candidates": [],
                    "proposal": None,
                    "verification_result": None,
                    "is_verified": False,
                    "missing_facts": [],
                    "detected_gaps": [],
                    "flags": [],
                    "status": "PENDING",
                }],
                "current_index": 0,
                "max_retries": 2,
                "time_budget_sec": 10.0,
                "start_time_monotonic": time.monotonic(),
                "total_retries": 0,
                "steps_log": [],
                "global_flags": [],
                "workflow_status": "RUNNING",
                "error_message": None,
            }

            final_state = compiled.invoke(initial_state)
            crit = final_state["criteria"][0]
            # Deterministic verifier flagged duration unestablished, which was enriched into missing_facts
            self.assertIn("duration dates", crit["missing_facts"])

    def test_contradiction_short_circuits_retries(self):
        """Verify that when a criterion is verified as CONTRADICTED, retries are immediately short-circuited."""
        with SessionLocal() as session:
            orchestrator = AgentOrchestrator(max_retries=3)
            raw_docs = session.query(DocumentModel).filter_by(patient_id="SYN-P003").all()
            raw_doc_dicts = [{"source_id": d.source_id, "patient_id": d.patient_id, "date": d.doc_date, "text": d.text} for d in raw_docs]

            compiled = orchestrator.build_graph(session, raw_doc_dicts)

            # Criterion C2 on SYN-P003 (patient explicitly declined PT)
            initial_state = {
                "case_id": "CASE-SYN-003",
                "patient_id": "SYN-P003",
                "policy_id": "SYN-POL-LMRI-001",
                "run_id": "TEST-CONTRA-001",
                "criteria": [{
                    "criterion_id": "C2",
                    "criterion_text": "Conservative treatment history is documented for at least six weeks",
                    "evidence_expectation": None,
                    "required_facts": ["Supervised physical therapy", "Duration >= 6 weeks"],
                    "min_duration_days": 42,
                    "query": "Conservative treatment",
                    "retrieval_round": 1,
                    "candidates": [],
                    "proposal": None,
                    "verification_result": None,
                    "is_verified": False,
                    "missing_facts": [],
                    "detected_gaps": [],
                    "flags": [],
                    "status": "PENDING",
                }],
                "current_index": 0,
                "max_retries": 3,
                "time_budget_sec": 10.0,
                "start_time_monotonic": time.monotonic(),
                "total_retries": 0,
                "steps_log": [],
                "global_flags": [],
                "workflow_status": "RUNNING",
                "error_message": None,
            }

            final_state = compiled.invoke(initial_state)
            crit = final_state["criteria"][0]
            # Since contradiction was verified in round 1, it must NOT have executed retry rounds 2 and 3
            self.assertEqual(crit["retrieval_round"], 1)
            self.assertEqual(crit["verification_result"]["status"], CriterionStatus.CONTRADICTED.value)

    def test_unsupported_met_proposal_downgraded(self):
        """Verify that proposed MET status without valid grounded evidence is downgraded to MISSING."""
        proposal = LLMCriterionProposal(
            criterion_id="C2",
            proposed_status="MET",
            confidence=0.99,
            evidence_quotes=[
                LLMEvidenceQuote(source_id="UNKNOWN-DOC-999", quote="Patient did 100 days of PT", polarity="SUPPORTING")
            ],
            missing_facts=[],
            detected_gaps=[],
            uncertainty_rationale="Hallucinated claim.",
        )

        candidates = [
            {"source_id": "SYN-P001-NOTE-01", "patient_id": "SYN-P001", "quote": "Real note text", "char_start": 0}
        ]

        valid_items, flags, downgraded_status = validate_and_ground_evidence(
            proposal=proposal,
            candidates=candidates,
            patient_id="SYN-P001",
        )

        self.assertEqual(downgraded_status, CriterionStatus.MISSING)
        self.assertEqual(len(valid_items), 0)
        self.assertIn("UNSUPPORTED_MET_DOWNGRADED_TO_MISSING", flags)

    def test_cross_patient_citation_rejected(self):
        """Verify that candidate quotes belonging to a different patient are rejected fail-closed."""
        proposal = LLMCriterionProposal(
            criterion_id="C1",
            proposed_status="MET",
            confidence=0.90,
            evidence_quotes=[
                LLMEvidenceQuote(source_id="FOREIGN-01", quote="Patient pain 8 weeks", polarity="SUPPORTING")
            ],
            missing_facts=[],
            detected_gaps=[],
            uncertainty_rationale="Cross-patient citation attempt.",
        )

        candidates = [
            {"source_id": "FOREIGN-01", "patient_id": "SYN-FOREIGN-PATIENT", "quote": "Patient pain 8 weeks", "char_start": 0}
        ]

        valid_items, flags, final_status = validate_and_ground_evidence(
            proposal=proposal,
            candidates=candidates,
            patient_id="SYN-P001",
        )

        self.assertEqual(len(valid_items), 0)
        self.assertTrue(any("CROSS_PATIENT_QUOTE_REJECTED" in f for f in flags))

    def test_symptom_negation_detected(self):
        """Verify that explicit symptom negation ('no back pain', 'denies back pain') evaluates to CONTRADICTED."""
        text = "Patient presented for routine checkup. No back pain reported. Vitals stable."
        pol, signals = detect_evidence_polarity(text, criterion_text="Documentation describes persistent low back symptoms")
        self.assertEqual(pol, EvidencePolarity.CONTRADICTING)
        self.assertTrue(any("SYMPTOM_NEGATION" in s for s in signals))

    def test_missing_credentials_fails_closed_without_fake(self):
        """Verify that GeminiProvider returns typed MISSING_API_KEY when key is absent and never fakes cloud calls."""
        provider = GeminiProvider(api_key=None)
        res = provider.generate_proposal(
            criterion_id="C1",
            criterion_text="Documentation describes persistent low back symptoms",
            patient_id="SYN-P001",
            required_facts=[],
            min_duration_days=None,
            candidates=[],
        )
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "MISSING_API_KEY")
        self.assertIsNone(res.proposal)
        self.assertTrue(res.is_external_llm)

    def test_socket_timeout_configured_on_gemini_client(self):
        """Verify that GeminiProvider sets types.HttpOptions timeout on genai.Client."""
        provider = GeminiProvider(api_key="TEST_MOCK_KEY", timeout_seconds=12.5)
        with patch("google.genai.Client") as mock_client:
            client = provider._get_client()
            mock_client.assert_called_once()
            _, kwargs = mock_client.call_args
            self.assertEqual(kwargs.get("api_key"), "TEST_MOCK_KEY")
            http_opts = kwargs.get("http_options")
            self.assertIsNotNone(http_opts)
            self.assertEqual(http_opts.timeout, 12500)

    def test_authority_boundary_inviolable(self):
        """Verify that orchestrator.run_case_workflow writes proposals to agent_proposals without touching criterion_results."""
        with SessionLocal() as session:
            before_results = session.query(CriterionResultModel).filter_by(case_id="CASE-SYN-001").all()
            before_statuses = {r.criterion_id: r.status for r in before_results}

            before_proposals_count = session.query(AgentProposalModel).filter_by(case_id="CASE-SYN-001").count()

            orchestrator = AgentOrchestrator()
            response = orchestrator.run_case_workflow(session, case_id="CASE-SYN-001")
            session.commit()

            after_results = session.query(CriterionResultModel).filter_by(case_id="CASE-SYN-001").all()
            after_statuses = {r.criterion_id: r.status for r in after_results}
            after_proposals_count = session.query(AgentProposalModel).filter_by(case_id="CASE-SYN-001").count()

            # Authoritative criterion_results must remain 100% unchanged
            self.assertEqual(before_statuses, after_statuses)
            # Proposals must be recorded in agent_proposals table
            self.assertGreater(after_proposals_count, before_proposals_count)

    def test_offline_benchmark_runner_deterministic(self):
        """Verify that run_comparative_agent_evaluation executes offline with 100% determinism and passes safety gates."""
        results = run_comparative_agent_evaluation(run_live_gemini=False)
        self.assertEqual(results["live_gemini_status"], "NOT RUN - API credentials not configured")
        self.assertFalse(results["external_llm_used"])

        b1 = results["benchmarks"]["benchmark1_verifier_fixtures"]
        self.assertEqual(b1["accuracy"], 1.0)
        self.assertEqual(b1["false_positive_met_after_gate"], 0)

        b2_stub = results["benchmarks"]["benchmark2_full_chart_stub"]
        self.assertEqual(b2_stub["accuracy"], 1.0)
        self.assertEqual(b2_stub["false_positive_met_after_gate"], 0)
        self.assertEqual(b2_stub["cross_patient_violations"], 0)

    def test_historical_vs_current_symptom_negation_regression(self):
        """Phase 12.1 Regression Test: Verify sentence-level temporal reconciliation for clinical negation."""
        crit_symptom = "Documentation describes persistent low back symptoms"
        crit_conservative = "Conservative treatment history is documented for at least six weeks"

        # 1. Historical negation reconciled with current positive symptom report
        p_reconciled = "Patient had no back pain in 2020. Currently reports severe low back pain for 8 weeks."
        pol1, sig1 = detect_evidence_polarity(p_reconciled, criterion_text=crit_symptom)
        self.assertEqual(pol1, EvidencePolarity.SUPPORTING)
        self.assertTrue(any("HISTORICAL_NEGATION_RECONCILED" in s for s in sig1))

        doc1 = {"source_id": "DOC-RECON", "patient_id": "SYN-P001", "text": p_reconciled}
        res1 = verify_criterion_evidence(
            criterion_id="C1",
            criterion_text=crit_symptom,
            patient_id="SYN-P001",
            candidate_evidence=[{"source_id": "DOC-RECON", "patient_id": "SYN-P001", "quote": p_reconciled}],
            raw_documents=[doc1],
            required_facts=["Low back pain"],
        )
        self.assertEqual(res1.status, CriterionStatus.MET)
        self.assertTrue(res1.verified)

        # 2. Pure historical negation without current positive symptom evidence
        p_hist_only = "Patient had no back pain in 2020."
        pol2, sig2 = detect_evidence_polarity(p_hist_only, criterion_text=crit_symptom)
        self.assertEqual(pol2, EvidencePolarity.UNCLEAR)
        self.assertTrue(any("HISTORICAL_NEGATION" in s for s in sig2))

        doc2 = {"source_id": "DOC-HIST-ONLY", "patient_id": "SYN-P001", "text": p_hist_only}
        res2 = verify_criterion_evidence(
            criterion_id="C1",
            criterion_text=crit_symptom,
            patient_id="SYN-P001",
            candidate_evidence=[{"source_id": "DOC-HIST-ONLY", "patient_id": "SYN-P001", "quote": p_hist_only}],
            raw_documents=[doc2],
            required_facts=["Low back pain"],
        )
        self.assertIn(res2.status, (CriterionStatus.AMBIGUOUS, CriterionStatus.MISSING))
        self.assertFalse(res2.verified)

        # 3. Active current negation must still be flagged CONTRADICTED
        p_current_neg = "Patient examined today and denies low back pain."
        pol3, sig3 = detect_evidence_polarity(p_current_neg, criterion_text=crit_symptom)
        self.assertEqual(pol3, EvidencePolarity.CONTRADICTING)

        doc3 = {"source_id": "DOC-CUR-NEG", "patient_id": "SYN-P001", "text": p_current_neg}
        res3 = verify_criterion_evidence(
            criterion_id="C1",
            criterion_text=crit_symptom,
            patient_id="SYN-P001",
            candidate_evidence=[{"source_id": "DOC-CUR-NEG", "patient_id": "SYN-P001", "quote": p_current_neg}],
            raw_documents=[doc3],
            required_facts=["Low back pain"],
        )
        self.assertEqual(res3.status, CriterionStatus.CONTRADICTED)
        self.assertFalse(res3.verified)

        # 4. Conflicting documents (Doc A positive, Doc B current negation)
        doc4a = {"source_id": "DOC-4A", "patient_id": "SYN-P001", "text": "Patient reports persistent low back pain for 10 weeks."}
        doc4b = {"source_id": "DOC-4B", "patient_id": "SYN-P001", "text": "Patient examined today and reports no back pain."}
        res4 = verify_criterion_evidence(
            criterion_id="C1",
            criterion_text=crit_symptom,
            patient_id="SYN-P001",
            candidate_evidence=[
                {"source_id": "DOC-4A", "patient_id": "SYN-P001", "quote": doc4a["text"]},
                {"source_id": "DOC-4B", "patient_id": "SYN-P001", "quote": doc4b["text"]},
            ],
            raw_documents=[doc4a, doc4b],
            required_facts=["Low back pain"],
        )
        self.assertEqual(res4.status, CriterionStatus.CONTRADICTED)
        self.assertIn("CONFLICTING_EVIDENCE_DETECTED", res4.validator_flags)

        # 5. Phrasing with non-symptom negation ("not relieved by rest")
        p_not_relieved = "Severe low back pain for 8 weeks is not relieved by rest or medication."
        doc5 = {"source_id": "DOC-5", "patient_id": "SYN-P001", "text": p_not_relieved}
        res5 = verify_criterion_evidence(
            criterion_id="C1",
            criterion_text=crit_symptom,
            patient_id="SYN-P001",
            candidate_evidence=[{"source_id": "DOC-5", "patient_id": "SYN-P001", "quote": p_not_relieved}],
            raw_documents=[doc5],
            required_facts=["Low back pain"],
        )
        self.assertEqual(res5.status, CriterionStatus.MET)
        self.assertTrue(res5.verified)

        # 6. Unrelated criteria (C2 physical therapy) are unaffected by symptom negation
        p_unrelated = "Patient had no back pain in 2020. Completed physical therapy July 1 through August 20, 2026."
        doc6 = {"source_id": "DOC-6", "patient_id": "SYN-P001", "text": p_unrelated}
        res6 = verify_criterion_evidence(
            criterion_id="C2",
            criterion_text=crit_conservative,
            patient_id="SYN-P001",
            candidate_evidence=[{"source_id": "DOC-6", "patient_id": "SYN-P001", "quote": p_unrelated}],
            raw_documents=[doc6],
            min_duration_days=42,
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
        )
        self.assertEqual(res6.status, CriterionStatus.MET)
        self.assertTrue(res6.verified)


if __name__ == "__main__":
    unittest.main()
