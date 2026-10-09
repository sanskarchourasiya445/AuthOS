"""Unit and integration tests for deterministic lexical retrieval baseline and evaluation."""
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
from backend.rag.evaluation import run_retrieval_benchmark
from backend.rag.ingest import ingest_synthetic_records
from backend.rag.retrieval import (
    BM25Okapi,
    retrieve_chart_candidates,
    retrieve_evidence_candidates,
    retrieve_policy_candidates,
    tokenize,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class RetrievalAlgorithmUnitTests(unittest.TestCase):
    """Pure unit tests for BM25 and tokenizer mechanics."""

    def test_tokenize_clean_and_filters_stopwords(self):
        tokens = tokenize("The patient has completed 6 weeks of physical therapy.")
        self.assertNotIn("the", tokens)
        self.assertNotIn("of", tokens)
        self.assertIn("patient", tokens)
        self.assertIn("completed", tokens)
        self.assertIn("physical", tokens)
        self.assertIn("therapy", tokens)

    def test_bm25_empty_query_or_corpus(self):
        bm25 = BM25Okapi([["lumbar", "pain"]])
        score, matched = bm25.score_document(0, [])
        self.assertEqual(score, 0.0)
        self.assertEqual(matched, [])

        empty_bm25 = BM25Okapi([])
        score, matched = empty_bm25.score_document(0, ["lumbar"])
        self.assertEqual(score, 0.0)
        self.assertEqual(matched, [])

    def test_bm25_scoring_monotonicity(self):
        corpus = [
            ["lumbar", "mri", "requested"],
            ["lumbar", "pain", "severe", "lumbar", "lumbar"],
            ["knee", "arthroscopy"],
        ]
        bm25 = BM25Okapi(corpus)
        score0, _ = bm25.score_document(0, ["lumbar"])
        score1, _ = bm25.score_document(1, ["lumbar"])
        score2, _ = bm25.score_document(2, ["lumbar"])

        self.assertGreater(score1, score0)
        self.assertEqual(score2, 0.0)


class RetrievalIntegrationTests(unittest.TestCase):
    """Integration tests verifying retrieval over PostgreSQL persisted chunks."""

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

    def test_ranking_determinism(self):
        """Repeated queries must return identical scores, ranks, and chunk IDs."""
        query = "supervised physical therapy conservative treatment"
        with self.SessionClass() as session:
            run1 = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            run2 = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)

            self.assertGreater(len(run1), 0)
            self.assertEqual(len(run1), len(run2))
            for c1, c2 in zip(run1, run2):
                self.assertEqual(c1.chunk_id, c2.chunk_id)
                self.assertEqual(c1.rank, c2.rank)
                self.assertEqual(c1.score, c2.score)
                self.assertEqual(c1.chunk_text, c2.chunk_text)

    def test_patient_isolation_zero_leakage(self):
        """Querying for SYN-P001 must NEVER return chunks belonging to SYN-P002 or SYN-P003."""
        # Query contains text uniquely present in SYN-P002 chart note ("attended several sessions")
        query = "attended several sessions exact start date and duration"
        with self.SessionClass() as session:
            results = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=5)

            # Every candidate returned must belong strictly to SYN-P001
            for cand in results:
                self.assertEqual(cand.patient_id, "SYN-P001")
                self.assertNotEqual(cand.patient_id, "SYN-P002")
                self.assertNotEqual(cand.patient_id, "SYN-P003")

    def test_source_provenance_and_exact_quote_preservation(self):
        """Candidates must preserve exact character offsets verifiable against raw document."""
        with self.SessionClass() as session:
            candidates = retrieve_chart_candidates(
                session, patient_id="SYN-P001", query="persistent low back pain", top_k=3
            )
            self.assertGreater(len(candidates), 0)

            for cand in candidates:
                raw_doc = session.query(DocumentModel).filter_by(source_id=cand.source_id).first()
                self.assertIsNotNone(raw_doc)
                # Verify exact offset slice
                self.assertEqual(raw_doc.text[cand.char_start:cand.char_end], cand.chunk_text)

    def test_policy_and_chart_separation(self):
        """Policy text and patient chart evidence must be retrieved independently."""
        with self.SessionClass() as session:
            result = retrieve_evidence_candidates(
                session,
                patient_id="SYN-P001",
                policy_id="SYN-POL-LMRI-001",
                query="conservative treatment six weeks",
                top_k=3,
            )

            # Chart candidates must contain only patient records
            self.assertGreater(len(result.chart_candidates), 0)
            for cc in result.chart_candidates:
                self.assertEqual(cc.patient_id, "SYN-P001")
                self.assertTrue(cc.source_id.startswith("SYN-P001"))

            # Policy candidates must contain only policy sections
            self.assertGreater(len(result.policy_candidates), 0)
            for pc in result.policy_candidates:
                self.assertEqual(pc.policy_id, "SYN-POL-LMRI-001")
                self.assertTrue(hasattr(pc, "heading"))

    def test_contradictory_evidence_retrieved_but_not_marked_met(self):
        """Lexical match on contradictory passage returns candidate without implying verification."""
        with self.SessionClass() as session:
            candidates = retrieve_chart_candidates(
                session,
                patient_id="SYN-P003",
                query="physical therapy offered conservative treatment",
                top_k=2,
            )
            self.assertGreater(len(candidates), 0)
            top_cand = candidates[0]
            self.assertEqual(top_cand.source_id, "SYN-P003-PT-02")
            # Text contains explicit refusal
            self.assertIn("declined physical therapy", top_cand.chunk_text)

    def test_empty_and_zero_match_queries(self):
        """Handling of whitespace, empty, and unrelated queries."""
        with self.SessionClass() as session:
            self.assertEqual(retrieve_chart_candidates(session, patient_id="SYN-P001", query=""), [])
            self.assertEqual(retrieve_chart_candidates(session, patient_id="SYN-P001", query="   "), [])
            self.assertEqual(
                retrieve_chart_candidates(session, patient_id="SYN-P001", query="completely_unrelated_nonsense_xyz"),
                [],
            )

    def test_synthetic_retrieval_benchmark_suite(self):
        """Execute the synthetic benchmark suite and verify zero cross-patient leakage."""
        with self.SessionClass() as session:
            report = run_retrieval_benchmark(session, k=3)
            self.assertEqual(report.total_cases, 6)
            self.assertEqual(report.cross_patient_violations, 0)
            self.assertGreaterEqual(report.mrr, 0.70)
            self.assertGreaterEqual(report.mean_recall_at_k, 0.75)


if __name__ == "__main__":
    unittest.main()
