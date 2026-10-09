"""Tests for the controlled dense and hybrid retrieval experiment."""
import os
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    AuditLogModel,
    Base,
    CaseModel,
    CriterionResultModel,
    DocumentChunkModel,
    DocumentModel,
    PolicyChunkModel,
    PolicyCriterionModel,
    PolicyModel,
)
from backend.db.seed import seed_synthetic_data
from backend.rag.dense_experiment import (
    retrieve_dense_chart_candidates,
    retrieve_hybrid_chart_candidates,
    run_comparative_retrieval_experiment,
)
from backend.rag.ingest import ingest_synthetic_records
from backend.rag.retrieval import retrieve_chart_candidates

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class DenseAndHybridExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
        cls.SessionClass = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        with self.SessionClass() as session:
            session.query(DocumentChunkModel).delete()
            session.query(PolicyChunkModel).delete()
            session.query(AuditLogModel).delete()
            session.query(CriterionResultModel).delete()
            session.query(CaseModel).delete()
            session.query(DocumentModel).delete()
            session.query(PolicyCriterionModel).delete()
            session.query(PolicyModel).delete()
            session.commit()
            seed_synthetic_data(session)
            ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

    def test_dense_candidate_provenance_and_offsets(self):
        """Every dense candidate preserves exact source character offsets verifiable against raw document."""
        with self.SessionClass() as session:
            candidates = retrieve_dense_chart_candidates(
                session, patient_id="SYN-P001", query="persistent low back pain", top_k=3
            )
            self.assertGreater(len(candidates), 0)

            for cand in candidates:
                self.assertEqual(cand.patient_id, "SYN-P001")
                self.assertEqual(cand.retrieval_method, "dense")
                raw_doc = session.query(DocumentModel).filter_by(source_id=cand.source_id).first()
                self.assertIsNotNone(raw_doc)
                self.assertEqual(raw_doc.text[cand.char_start:cand.char_end], cand.chunk_text)

    def test_dense_patient_isolation_zero_leakage(self):
        """Dense embedding retrieval must strictly isolate patient charts."""
        adversarial_query = "attended several sessions exact start date and duration"
        with self.SessionClass() as session:
            candidates = retrieve_dense_chart_candidates(
                session, patient_id="SYN-P001", query=adversarial_query, top_k=5
            )
            for cand in candidates:
                self.assertEqual(cand.patient_id, "SYN-P001")
                self.assertNotEqual(cand.patient_id, "SYN-P002")
                self.assertNotEqual(cand.patient_id, "SYN-P003")

    def test_dense_bridges_synonym_mismatch_where_bm25_fails(self):
        """Proves hypothesis: dense embeddings bridge vocabulary mismatch when BM25 returns 0."""
        query = "ambulation assistance and non operative rehabilitation regimen"
        with self.SessionClass() as session:
            # BM25 baseline fails due to 0 token overlap
            bm25_cands = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            self.assertEqual(len(bm25_cands), 0)

            # Dense retrieval successfully finds the physical therapy document
            dense_cands = retrieve_dense_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            self.assertGreater(len(dense_cands), 0)
            dense_sources = [c.source_id for c in dense_cands]
            self.assertIn("SYN-P001-PT-02", dense_sources)

    def test_hybrid_rrf_scoring_and_determinism(self):
        """Hybrid RRF produces deterministic ranking and candidate lists."""
        query = "conservative treatment physical therapy duration"
        with self.SessionClass() as session:
            run1 = retrieve_hybrid_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            run2 = retrieve_hybrid_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)

            self.assertEqual(len(run1), len(run2))
            for c1, c2 in zip(run1, run2):
                self.assertEqual(c1.chunk_id, c2.chunk_id)
                self.assertEqual(c1.score, c2.score)
                self.assertEqual(c1.rank, c2.rank)
                self.assertEqual(c1.retrieval_method, "hybrid_rrf")

    def test_comparative_experiment_execution(self):
        """Run the full 3-way comparative benchmark suite and verify zero violations."""
        with self.SessionClass() as session:
            report = run_comparative_retrieval_experiment(session, k=3)
            self.assertIn("bm25", report)
            self.assertIn("dense", report)
            self.assertIn("hybrid", report)

            # Assert zero cross-patient leakage across all 3 methods
            self.assertEqual(report["bm25"].cross_patient_violations, 0)
            self.assertEqual(report["dense"].cross_patient_violations, 0)
            self.assertEqual(report["hybrid"].cross_patient_violations, 0)

            # Assert all 3 methods evaluated identical 7 quality cases
            self.assertEqual(report["bm25"].quality_cases_count, 7)
            self.assertEqual(report["dense"].quality_cases_count, 7)
            self.assertEqual(report["hybrid"].quality_cases_count, 7)


if __name__ == "__main__":
    unittest.main()
