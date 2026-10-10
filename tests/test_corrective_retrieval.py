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
