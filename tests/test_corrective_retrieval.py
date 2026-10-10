"""Tests for bounded corrective retrieval and abstention safety (Phase 5B).

Verifies invariants:
1. Bounded attempt budget: never exceeds max_retries + 1.
2. Candidate capping and deduplication: strictly <= top_k unique chunks.
3. Early stop condition: stops immediately on attempt 0 when candidates exist.
4. Synonym mismatch recovery: recovers missing evidence for known domain rewrites.
5. Clean abstention on negative controls: returns 0 candidates for off-domain / unsupported queries.
6. Patient boundary isolation: 0 foreign patient records on any attempt.
7. Determinism: identical results across repeated runs.
8. Downstream safety: retrieved candidates never trigger false-positive MET in verifier.
"""
import os
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contracts.schemas import CriterionStatus
from backend.db.seed import seed_synthetic_data
from backend.rag.ingest import ingest_synthetic_records
from backend.rag.corrective import (
    retrieve_chart_candidates_bounded_corrective,
    rewrite_query_deterministic,
    DETERMINISTIC_SYNONYM_RULES,
)
from backend.verification.engine import verify_criterion_evidence

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class BoundedCorrectiveRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
        cls.SessionLocal = sessionmaker(bind=cls.engine)
        with cls.SessionLocal() as session:
            seed_synthetic_data(session)
            ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

    def test_bounded_attempt_budget_invariant(self):
        """Retrieval must never exceed max_retries + 1 attempts regardless of query."""
        with self.SessionLocal() as session:
            # Query with zero matches and max_retries=2 -> max 3 attempts
            cands, audit = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="completely ungrounded non matching query terms xyz",
                top_k=3,
                max_retries=2,
            )
            self.assertLessEqual(audit.attempts_executed, 3)
            self.assertEqual(len(cands), 0)

            # Query with max_retries=0 -> exactly 1 attempt
            cands, audit_0 = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="completely ungrounded non matching query terms xyz",
                top_k=3,
                max_retries=0,
            )
            self.assertEqual(audit_0.attempts_executed, 1)

    def test_candidate_capping_and_deduplication(self):
        """Returned candidates must never exceed top_k and must be deduplicated by chunk_id."""
        with self.SessionLocal() as session:
            cands, audit = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="persistent low back pain physical therapy",
                top_k=2,
                max_retries=2,
            )
            self.assertLessEqual(len(cands), 2)
            chunk_ids = [c.chunk_id for c in cands]
            self.assertEqual(len(chunk_ids), len(set(chunk_ids)), "Chunks must be deduplicated")

    def test_candidate_capping_strict_top_k(self):
        """Candidate count must strictly equal top_k when more candidates are available."""
        with self.SessionLocal() as session:
            cands, _ = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="persistent low back pain physical therapy",
                top_k=1,
                max_retries=2,
            )
            self.assertEqual(len(cands), 1)

    def test_early_stop_condition_on_initial_hit(self):
        """If attempt 0 returns candidates, the corrective loop must terminate immediately."""
        with self.SessionLocal() as session:
            cands, audit = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="physical therapy persistent symptoms",
                top_k=3,
                max_retries=2,
            )
            self.assertGreater(len(cands), 0)
            self.assertEqual(audit.attempts_executed, 1, "Must stop on attempt 0")
            self.assertTrue(audit.history[0].stopped)

    def test_synonym_mismatch_recovery(self):
        """Query with clinical synonyms recovers relevant evidence on attempt 1."""
        with self.SessionLocal() as session:
            query = "ambulation assistance and non operative rehabilitation regimen"
            cands, audit = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query=query,
                top_k=3,
                max_retries=2,
            )
            self.assertGreater(len(cands), 0)
            self.assertEqual(audit.attempts_executed, 2, "Must recover on attempt 1 (retry 1)")
            retrieved_sources = [c.source_id for c in cands]
            self.assertIn("SYN-P001-PT-02", retrieved_sources)

    def test_negative_controls_clean_abstention(self):
        """Negative controls and off-domain queries must abstain with 0 candidates."""
        with self.SessionLocal() as session:
            # Negative control: coronary artery bypass
            cands_cardiac, audit_c = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="coronary artery bypass graft cardiopulmonary bypass hemodynamics",
                top_k=3,
                max_retries=2,
            )
            self.assertEqual(len(cands_cardiac), 0, "Off-domain query must return 0 candidates")

            # Negative control: unsupported motor deficit
            cands_neuro, audit_n = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="progressive motor deficit rapid motor weakness cauda equina",
                top_k=3,
                max_retries=2,
            )
            self.assertEqual(len(cands_neuro), 0, "Unsupported query must return 0 candidates")

            # Cross-patient query text: terms from SYN-P002 queried against SYN-P001
            cands_cross, audit_x = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="attended several sessions exact start date and duration are not documented",
                top_k=3,
                max_retries=2,
            )
            self.assertEqual(len(cands_cross), 0, "Cross-patient query text must abstain with 0 candidates")

    def test_strict_patient_isolation_invariant(self):
        """Every returned candidate must strictly belong to the specified patient."""
        with self.SessionLocal() as session:
            for pid in ["SYN-P001", "SYN-P002", "SYN-P003"]:
                cands, _ = retrieve_chart_candidates_bounded_corrective(
                    session,
                    patient_id=pid,
                    query="pain therapy treatment symptoms",
                    top_k=5,
                    max_retries=2,
                )
                for cand in cands:
                    self.assertEqual(
                        cand.patient_id,
                        pid,
                        f"Patient isolation breach: candidate {cand.chunk_id} has {cand.patient_id} != {pid}",
                    )

    def test_determinism_across_repeat_runs(self):
        """Repeated executions on identical inputs must produce identical candidates and audit history."""
        with self.SessionLocal() as session:
            query = "ambulation assistance and non operative rehabilitation regimen"
            run1, audit1 = retrieve_chart_candidates_bounded_corrective(
                session, patient_id="SYN-P001", query=query, top_k=3
            )
            run2, audit2 = retrieve_chart_candidates_bounded_corrective(
                session, patient_id="SYN-P001", query=query, top_k=3
            )

            self.assertEqual([c.chunk_id for c in run1], [c.chunk_id for c in run2])
            self.assertEqual([c.source_id for c in run1], [c.source_id for c in run2])
            self.assertEqual(audit1.attempts_executed, audit2.attempts_executed)

    def test_downstream_verifier_safety_with_retrieved_candidates(self):
        """Candidates from corrective retrieval passed to the verifier must never produce false-positive MET."""
        with self.SessionLocal() as session:
            # Query contradictory case for SYN-P003 (declined PT)
            cands, _ = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P003",
                query="physical therapy offered conservative treatment",
                top_k=3,
            )
            self.assertGreater(len(cands), 0)

            # Pass candidates to verifier
            candidate_evidence = [
                {
                    "source_id": c.source_id,
                    "patient_id": c.patient_id,
                    "quote": c.chunk_text,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                }
                for c in cands
            ]
            raw_docs = [
                {
                    "source_id": c.source_id,
                    "patient_id": c.patient_id,
                    "text": c.chunk_text,
                }
                for c in cands
            ]

            res = verify_criterion_evidence(
                criterion_id="C2",
                criterion_text="Conservative treatment history is documented for at least six weeks",
                patient_id="SYN-P003",
                candidate_evidence=candidate_evidence,
                raw_documents=raw_docs,
                min_duration_days=42,
            )

            # Must be CONTRADICTED or MISSING, NEVER MET!
            self.assertNotEqual(res.status, CriterionStatus.MET)
            self.assertFalse(res.verified)
            self.assertEqual(res.status, CriterionStatus.CONTRADICTED)

    def test_empty_query_and_whitespace_abstention(self):
        """Empty queries, pure whitespace, or nonexistent patient IDs must abstain with 0 candidates."""
        with self.SessionLocal() as session:
            for bad_query in ["", "   ", "\t\r\n", "   \n "]:
                cands, audit = retrieve_chart_candidates_bounded_corrective(
                    session,
                    patient_id="SYN-P001",
                    query=bad_query,
                    top_k=3,
                    max_retries=2,
                )
                self.assertEqual(len(cands), 0)
                self.assertEqual(audit.candidates, [])

            # Nonexistent patient ID
            cands_none, audit_none = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="NONEXISTENT-PATIENT",
                query="physical therapy persistent symptoms",
                top_k=3,
                max_retries=2,
            )
            self.assertEqual(len(cands_none), 0)

    def test_attempt_budget_exhaustion_graceful(self):
        """Attempt budget exhaustion must record all history and never raise exceptions."""
        with self.SessionLocal() as session:
            # Query that cannot match even after rewrites
            cands, audit = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query="unobtainium superconducting particle physics",
                top_k=3,
                max_retries=2,
            )
            self.assertEqual(len(cands), 0)
            self.assertLessEqual(audit.attempts_executed, 3)
            self.assertEqual(audit.total_attempts_budget, 3)
            self.assertTrue(len(audit.history) > 0)
            self.assertTrue(audit.history[-1].stopped)

    def test_candidate_retrieval_alone_never_sets_met_in_workflow(self):
        """Retrieving candidates alone must never produce MET status in workflow or DB."""
        from backend.workflow.evaluator import evaluate_case
        from backend.db.models import CriterionResultModel

        with self.SessionLocal() as session:
            # Evaluate SYN-P003 (declined PT)
            packet = evaluate_case("CASE-SYN-003", session)
            self.assertIsNotNone(packet)

            # In the DB, C2 must NOT be MET
            c2_res = (
                session.query(CriterionResultModel)
                .filter_by(case_id="CASE-SYN-003", criterion_id="C2")
                .first()
            )
            self.assertIsNotNone(c2_res)
            self.assertNotEqual(c2_res.status, "MET")
            self.assertFalse(c2_res.verified)
            self.assertEqual(c2_res.status, "CONTRADICTED")

    def test_invalid_max_retries_raises_value_error(self):
        """Values of max_retries < 0 or > 5 must raise ValueError."""
        with self.SessionLocal() as session:
            with self.assertRaises(ValueError):
                retrieve_chart_candidates_bounded_corrective(
                    session, patient_id="SYN-P001", query="test query", max_retries=-1
                )
            with self.assertRaises(ValueError):
                retrieve_chart_candidates_bounded_corrective(
                    session, patient_id="SYN-P001", query="test query", max_retries=6
                )

    def test_root_keyword_extraction_when_synonym_rewrite_inapplicable(self):
        """When Attempt 1 has no synonym rule, loop must advance to Attempt 2 root keyword extraction."""
        with self.SessionLocal() as session:
            # Query has stopwords and off-domain terms that do not trigger any synonym rule
            query = "unobtainium particle physics with attended sessions"
            cands, audit = retrieve_chart_candidates_bounded_corrective(
                session,
                patient_id="SYN-P001",
                query=query,
                top_k=3,
                max_retries=2,
            )
            self.assertEqual(len(cands), 0)

            # Reconciled execution: Attempt 0 ran, Attempt 1 recorded no rewrite, Attempt 2 extracted root keywords
            self.assertEqual(audit.attempts_executed, 3)
            self.assertEqual(len(audit.history), 3)
            self.assertFalse(audit.history[0].stopped)
            self.assertFalse(audit.history[1].stopped)
            self.assertEqual(audit.history[1].reason, "No deterministic rewrite rule applicable for attempt 1")
            self.assertTrue(audit.history[2].stopped)
            self.assertEqual(audit.history[2].query_used, "unobtainium particle physics sessions")
            self.assertEqual(audit.history[2].reason, "Corrective retry 2 returned 0 candidates")

    def test_settings_validates_max_retrieval_retries(self):
        """Settings must validate max_retrieval_retries limits and default enable_corrective_retrieval to False."""
        from pydantic import ValidationError
        from backend.config import Settings

        # Default configuration
        s_default = Settings()
        self.assertFalse(s_default.enable_corrective_retrieval)
        self.assertEqual(s_default.max_retrieval_retries, 2)

        # Valid custom limits
        s_valid = Settings(max_retrieval_retries=4, enable_corrective_retrieval=True)
        self.assertEqual(s_valid.max_retrieval_retries, 4)
        self.assertTrue(s_valid.enable_corrective_retrieval)

        # Invalid bounds (< 0 or > 5)
        with self.assertRaises(ValidationError):
            Settings(max_retrieval_retries=-1)
        with self.assertRaises(ValidationError):
            Settings(max_retrieval_retries=10)


