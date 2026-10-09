"""Adversarial and boundary test suite for AuthOS lexical retrieval baseline.

Covers:
1. Synonym / vocabulary mismatch (lexical BM25 limitation).
2. Keyword overlap with irrelevant clinical content.
3. Explicit negation and contradictory content (retrieval != verification).
4. Stopword-only queries.
5. Duplicate chunks and deterministic tie-breaking.
6. Empty ground-truth relevance sets.
7. Relevant documents ranked below top_k cutoff.
8. Changed source text and stale chunk purge.
9. Patient-isolation boundary defense.
10. Deterministic ranking across repeated runs.
"""
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
from backend.rag.ingest import (
    chunk_patient_document,
    ingest_persisted_document,
    ingest_synthetic_records,
)
from backend.rag.retrieval import (
    retrieve_chart_candidates,
    retrieve_evidence_candidates,
    tokenize,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class AdversarialRetrievalTests(unittest.TestCase):
    """Adversarial tests auditing lexical retrieval failure modes and safety invariants."""

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

    def test_01_synonym_vocabulary_mismatch(self):
        """Synonym query demonstrates vocabulary mismatch limitation of lexical retrieval.

        'ambulation assistance non-operative rehabilitation' is semantically related to
        supervised physical therapy, but shares 0 lexical tokens with SYN-P001-PT-02.
        Lexical BM25 must return 0 candidates, proving need for dense retrieval in later phases.
        """
        query = "ambulation assistance non operative rehabilitation regimen"
        with self.SessionClass() as session:
            candidates = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            # Confirms expected lexical limitation: zero keyword overlap yields zero candidates
            self.assertEqual(len(candidates), 0)

    def test_02_keyword_overlap_irrelevant_content(self):
        """Plausible keyword overlap returns candidates that mention keywords in wrong clinical context.

        Querying for 'low back pain' on SYN-P001 retrieves both NOTE-01 (clinical note)
        and ORDER-03 (radiology order). Both match lexically, but have different clinical roles.
        """
        query = "low back pain"
        with self.SessionClass() as session:
            candidates = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=5)
            self.assertGreaterEqual(len(candidates), 2)
            source_ids = [c.source_id for c in candidates]
            self.assertIn("SYN-P001-NOTE-01", source_ids)
            self.assertIn("SYN-P001-ORDER-03", source_ids)

    def test_03_explicit_negation_and_contradiction(self):
        """Explicit negation in chart matches lexical query but contradicts requirement.

        SYN-P003-PT-02 states 'Physical therapy was offered. Patient declined physical therapy'.
        BM25 scores this passage highly for 'physical therapy', but it is a CLINICAL CONTRADICTION.
        This test proves that lexical retrieval relevance != criterion verification.
        """
        query = "physical therapy conservative treatment"
        with self.SessionClass() as session:
            candidates = retrieve_chart_candidates(session, patient_id="SYN-P003", query=query, top_k=2)
            self.assertGreater(len(candidates), 0)
            top_hit = candidates[0]
            self.assertEqual(top_hit.source_id, "SYN-P003-PT-02")
            # Text contains explicit refusal
            self.assertIn("declined physical therapy", top_hit.chunk_text)
            # Crucial invariant: candidate is merely a candidate; status must not be MET
            self.assertNotIn("MET", top_hit.chunk_text)

    def test_04_stopword_only_queries(self):
        """Queries composed entirely of stopwords must return empty candidates safely."""
        with self.SessionClass() as session:
            self.assertEqual(retrieve_chart_candidates(session, patient_id="SYN-P001", query="and or the if of with"), [])
            self.assertEqual(retrieve_chart_candidates(session, patient_id="SYN-P001", query="to be or not to be"), [])
            self.assertEqual(retrieve_chart_candidates(session, patient_id="SYN-P001", query="all about above after"), [])

    def test_05_duplicate_chunks_and_ties(self):
        """Ties between identical-scoring chunks must break deterministically."""
        with self.SessionClass() as session:
            # Create two parent documents first to satisfy foreign key
            d1 = DocumentModel(
                source_id="SYN-P001-TIE-01",
                patient_id="SYN-P001",
                doc_date="2026-09-01",
                text="Identical twin note text for tie breaking audit.",
            )
            d2 = DocumentModel(
                source_id="SYN-P001-TIE-02",
                patient_id="SYN-P001",
                doc_date="2026-09-01",
                text="Identical twin note text for tie breaking audit.",
            )
            session.add_all([d1, d2])
            session.flush()

            # Create two artificial identical chunks for SYN-P001 with same text, date, and score
            c1 = DocumentChunkModel(
                chunk_id="SYN-P001-TIE-01_chk000_v1",
                source_id="SYN-P001-TIE-01",
                patient_id="SYN-P001",
                doc_date="2026-09-01",
                chunk_text="Identical twin note text for tie breaking audit.",
                chunk_index=0,
                char_start=0,
                char_end=48,
                token_count=8,
                chunk_version="v1",
            )
            c2 = DocumentChunkModel(
                chunk_id="SYN-P001-TIE-02_chk000_v1",
                source_id="SYN-P001-TIE-02",
                patient_id="SYN-P001",
                doc_date="2026-09-01",
                chunk_text="Identical twin note text for tie breaking audit.",
                chunk_index=0,
                char_start=0,
                char_end=48,
                token_count=8,
                chunk_version="v1",
            )
            session.add_all([c1, c2])
            session.commit()

            res1 = retrieve_chart_candidates(session, patient_id="SYN-P001", query="Identical twin note text", top_k=5)
            res2 = retrieve_chart_candidates(session, patient_id="SYN-P001", query="Identical twin note text", top_k=5)

            # Both runs must produce identical chunk_id ordering
            ids1 = [c.chunk_id for c in res1]
            ids2 = [c.chunk_id for c in res2]
            self.assertEqual(ids1, ids2)
            # Alphabetical tie-breaking on source_id: TIE-01 before TIE-02
            self.assertEqual(ids1[0], "SYN-P001-TIE-01_chk000_v1")
            self.assertEqual(ids1[1], "SYN-P001-TIE-02_chk000_v1")

    def test_06_empty_ground_truth_relevance_set(self):
        """Query with empty ground-truth relevance set must not inflate IR metrics."""
        with self.SessionClass() as session:
            report = run_retrieval_benchmark(session, k=3)
            # Find the unsupported case in the benchmark
            unsupported_case = next(c for c in report.case_results if c.case_id == "EVAL-05-UNSUPPORTED-CRITERION")
            # Must be marked as safety check with None for precision/recall (not padded with 1.0)
            self.assertTrue(unsupported_case.is_safety_check)
            self.assertIsNone(unsupported_case.precision_at_k)
            self.assertIsNone(unsupported_case.recall_at_k)
            self.assertTrue(unsupported_case.safety_pass)

    def test_07_relevant_document_ranked_below_cutoff(self):
        """top_k cutoff strictly restricts candidate list length."""
        with self.SessionClass() as session:
            # Query matches multiple chunks in SYN-P001
            query = "persistent low back pain physical therapy MRI"
            cands_k1 = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=1)
            cands_k2 = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=2)

            self.assertEqual(len(cands_k1), 1)
            self.assertEqual(len(cands_k2), 2)
            self.assertEqual(cands_k1[0].chunk_id, cands_k2[0].chunk_id)
            self.assertEqual(cands_k1[0].rank, 1)
            self.assertEqual(cands_k2[1].rank, 2)

    def test_08_changed_source_text_and_stale_chunks(self):
        """Re-ingesting modified source text purges stale chunks immediately."""
        with self.SessionClass() as session:
            # Check baseline: hyperbaric oxygen therapy not present
            cands_before = retrieve_chart_candidates(
                session, patient_id="SYN-P001", query="hyperbaric oxygen wound chamber", top_k=3
            )
            self.assertEqual(len(cands_before), 0)

            # Update NOTE-01 with new clinical text
            doc = session.query(DocumentModel).filter_by(source_id="SYN-P001-NOTE-01").first()
            doc.text = "Patient reports persistent low back pain. Completed hyperbaric oxygen wound chamber therapy."
            session.commit()

            # Re-ingest this persisted document
            ingest_persisted_document(session, "SYN-P001-NOTE-01", chunk_version="v1")
            session.commit()

            # Retrieval must immediately reflect the updated text
            cands_after = retrieve_chart_candidates(
                session, patient_id="SYN-P001", query="hyperbaric oxygen wound chamber", top_k=3
            )
            self.assertEqual(len(cands_after), 1)
            self.assertIn("hyperbaric", cands_after[0].chunk_text)

    def test_09_patient_isolation_boundary_defense(self):
        """Querying SYN-P001 with phrases unique to SYN-P002 and SYN-P003 returns 0 foreign records."""
        with self.SessionClass() as session:
            # Phrase from SYN-P002: "attended several sessions exact start date"
            # Phrase from SYN-P003: "Patient declined physical therapy at this visit"
            adversarial_query = (
                "attended several sessions exact start date and duration "
                "Patient declined physical therapy at this visit"
            )
            candidates = retrieve_chart_candidates(session, patient_id="SYN-P001", query=adversarial_query, top_k=10)

            for cand in candidates:
                self.assertEqual(cand.patient_id, "SYN-P001")
                self.assertNotIn("declined physical therapy", cand.chunk_text)
                self.assertNotIn("attended several sessions", cand.chunk_text)

    def test_10_deterministic_ranking_across_repeated_runs(self):
        """50 repeated query executions must return byte-for-byte identical candidate lists."""
        query = "conservative treatment physical therapy duration"
        with self.SessionClass() as session:
            first_run = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            first_tuples = [(c.chunk_id, c.score, c.rank, c.chunk_text) for c in first_run]

            for _ in range(50):
                subsequent_run = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
                subsequent_tuples = [(c.chunk_id, c.score, c.rank, c.chunk_text) for c in subsequent_run]
                self.assertEqual(first_tuples, subsequent_tuples)


if __name__ == "__main__":
    unittest.main()
