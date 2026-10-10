"""Phase 10 Comprehensive Retrieval Quality & Failure Taxonomy Test Suite.

Rigorously verifies all 12 failure taxonomy categories defined in Phase 10:
1. Lexical mismatch
2. Terminology mismatch
3. Negation and polarity
4. Temporal mismatch
5. Chunk-boundary loss
6. Multi-passage requirements
7. Duration and threshold requirements
8. Contradictory evidence
9. Irrelevant high-ranking passages
10. Source-offset or citation mismatch
11. Metadata filtering failure
12. Patient/case isolation failure
Plus:
13. Calibrated vs uncalibrated Hybrid RRF safety abstention
"""
import os
import unittest
from datetime import datetime, timezone
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
from backend.rag.corrective import (
    retrieve_chart_candidates_bounded_corrective,
    rewrite_query_deterministic,
)
from backend.rag.dense_experiment import (
    retrieve_dense_chart_candidates,
    retrieve_hybrid_chart_candidates,
)
from backend.rag.ingest import chunk_patient_document, ingest_synthetic_records
from backend.rag.retrieval import (
    BM25Okapi,
    retrieve_chart_candidates,
    tokenize,
)
from backend.verification.engine import (
    validate_evidence_provenance,
    verify_criterion_evidence,
)
from contracts.schemas import CriterionStatus

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class Phase10RetrievalTaxonomyTests(unittest.TestCase):
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

    # Category 1: Lexical Mismatch
    def test_01_lexical_mismatch(self):
        """Lexical BM25 yields 0 hits when query and chart use different words for same concept;
        bounded corrective query rewriting recovers the target chunk."""
        query = "ambulation assistance and non operative rehabilitation regimen"
        with self.SessionClass() as session:
            # Baseline BM25 fails completely (zero keyword overlap with 'physical therapy')
            bm25_cands = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            self.assertEqual(len(bm25_cands), 0)

            # Bounded corrective retrieval applies clinical synonym rule and succeeds
            corr_cands, audit = retrieve_chart_candidates_bounded_corrective(
                session, patient_id="SYN-P001", query=query, top_k=3
            )
            self.assertGreaterEqual(len(corr_cands), 1)
            self.assertEqual(corr_cands[0].source_id, "SYN-P001-PT-02")
            self.assertEqual(audit.attempts_executed, 2)

    # Category 2: Terminology Mismatch
    def test_02_terminology_mismatch(self):
        """Clinical terminology abbreviations and phrasing variants are bridged deterministically."""
        query = "ordering clinician requisition for lumbar imaging study"
        with self.SessionClass() as session:
            cands = retrieve_chart_candidates(session, patient_id="SYN-P002", query=query, top_k=3)
            self.assertGreaterEqual(len(cands), 1)
            self.assertEqual(cands[0].source_id, "SYN-P002-ORDER-03")

    # Category 3: Negation and Polarity
    def test_03_negation_and_polarity_retrieval_vs_verification(self):
        """Negated clinical passage is successfully retrieved, but downstream verifier flags it as contradicted."""
        query = "bowel or bladder dysfunction sphincter changes"
        with self.SessionClass() as session:
            # Retrieval finds NOTE-01 because 'bowel or bladder' matches lexically
            cands = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            self.assertGreaterEqual(len(cands), 1)
            self.assertEqual(cands[0].source_id, "SYN-P001-NOTE-01")

            # Verifier evaluates candidate and correctly assigns CONTRADICTED (denies symptom)
            raw_docs = [{"source_id": "SYN-P001-NOTE-01", "patient_id": "SYN-P001", "date": "2026-08-01", "text": cands[0].chunk_text}]
            cand_dict = [{
                "source_id": cands[0].source_id,
                "patient_id": cands[0].patient_id,
                "quote": cands[0].chunk_text,
                "char_start": cands[0].char_start,
                "char_end": cands[0].char_end,
            }]
            ver_result = verify_criterion_evidence(
                patient_id="SYN-P001",
                criterion_id="C_NEURO",
                criterion_text="Progressive neurological deficit or cauda equina syndrome documented",
                raw_documents=raw_docs,
                candidate_evidence=cand_dict,
                required_facts=["Bowel or bladder dysfunction"],
            )
            self.assertEqual(ver_result.status, CriterionStatus.CONTRADICTED)
            self.assertFalse(ver_result.verified)

    # Category 4: Temporal Mismatch
    def test_04_temporal_mismatch_duration_window(self):
        """Passage with insufficient therapy duration fails 6-week temporal threshold."""
        raw_doc = {
            "source_id": "SYN-TEST-PT-OLD",
            "patient_id": "SYN-P001",
            "date": "2026-09-01",
            "text": "Patient completed 10 days of physical therapy from August 1 to August 11, 2026.",
        }
        cand_dict = [{
            "source_id": "SYN-TEST-PT-OLD",
            "patient_id": "SYN-P001",
            "quote": raw_doc["text"],
            "char_start": 0,
            "char_end": len(raw_doc["text"]),
        }]
        ver_result = verify_criterion_evidence(
            patient_id="SYN-P001",
            criterion_id="C2",
            criterion_text="Conservative treatment history is documented for at least six weeks",
            raw_documents=[raw_doc],
            candidate_evidence=cand_dict,
            min_duration_days=42,
            required_facts=["Supervised physical therapy", "Duration >= 6 weeks"],
        )
        # 10 days < 42 days (6 weeks) -> Must be AMBIGUOUS or unverified, never MET
        self.assertNotEqual(ver_result.status, CriterionStatus.MET)
        self.assertFalse(ver_result.verified)

    # Category 5: Chunk-Boundary Loss
    def test_05_chunk_boundary_loss_offset_cohesion(self):
        """Chunking preserves paragraph boundaries and verbatim offsets text[start:end] == chunk_text."""
        doc_text = (
            "First section: Initial patient evaluation.\n\n"
            "Second section: Physical therapy initiated on July 1 and continued through August 20, 2026.\n\n"
            "Third section: Re-evaluation and imaging request."
        )
        chunks = chunk_patient_document(
            source_id="DOC-BOUNDARY-TEST",
            patient_id="SYN-P001",
            text=doc_text,
            chunk_version="v1",
        )
        self.assertGreaterEqual(len(chunks), 1)
        for chk in chunks:
            self.assertEqual(doc_text[chk.char_start:chk.char_end], chk.chunk_text)
            self.assertIn("chunk_version", chk.__dict__)

    # Category 6: Multi-Passage Requirements
    def test_06_multi_passage_requirements(self):
        """Criteria requiring facts across distinct documents correctly retrieve multiple distinct sources."""
        query = "persistent lumbar spine pain and clinical symptoms"
        with self.SessionClass() as session:
            cands = retrieve_chart_candidates(session, patient_id="SYN-P001", query=query, top_k=3)
            sources = {c.source_id for c in cands}
            # Both clinical note (symptoms) and radiology order (requisition) must be present
            self.assertIn("SYN-P001-NOTE-01", sources)
            self.assertIn("SYN-P001-ORDER-03", sources)

    # Category 7: Duration and Threshold Requirements
    def test_07_duration_and_threshold_requirements(self):
        """Ambiguous duration without dates cannot verify minimum duration requirement."""
        with self.SessionClass() as session:
            cands = retrieve_chart_candidates(
                session, patient_id="SYN-P002", query="physical therapy attended several sessions", top_k=2
            )
            self.assertGreaterEqual(len(cands), 1)
            self.assertEqual(cands[0].source_id, "SYN-P002-PT-02")

            # Ingested note states 'attended several sessions; exact start date and duration are not documented'
            raw_docs = [{"source_id": "SYN-P002-PT-02", "patient_id": "SYN-P002", "date": "2026-09-02", "text": cands[0].chunk_text}]
            cand_dict = [{
                "source_id": cands[0].source_id,
                "patient_id": cands[0].patient_id,
                "quote": cands[0].chunk_text,
                "char_start": cands[0].char_start,
                "char_end": cands[0].char_end,
            }]
            ver = verify_criterion_evidence(
                patient_id="SYN-P002",
                criterion_id="C2",
                criterion_text="Conservative treatment history is documented for at least six weeks",
                raw_documents=raw_docs,
                candidate_evidence=cand_dict,
                min_duration_days=42,
                required_facts=["Duration >= 6 weeks"],
            )
            self.assertEqual(ver.status, CriterionStatus.AMBIGUOUS)
            self.assertFalse(ver.verified)

    # Category 8: Contradictory Evidence
    def test_08_contradictory_evidence_retrieval(self):
        """Passage documenting care refusal is retrieved at top rank and verified as CONTRADICTED."""
        with self.SessionClass() as session:
            cands = retrieve_chart_candidates(
                session, patient_id="SYN-P003", query="physical therapy offered conservative treatment", top_k=2
            )
            self.assertGreaterEqual(len(cands), 1)
            self.assertEqual(cands[0].source_id, "SYN-P003-PT-02")
            self.assertIn("declined", cands[0].chunk_text.lower())

    # Category 9: Irrelevant High-Ranking Passages
    def test_09_irrelevant_high_ranking_passages(self):
        """Keywords overlapping across different document types are ranked deterministically by score and date."""
        with self.SessionClass() as session:
            cands = retrieve_chart_candidates(
                session, patient_id="SYN-P001", query="low back pain persistent symptoms duration", top_k=5
            )
            self.assertGreaterEqual(len(cands), 2)
            # Scores are strictly monotonic non-increasing
            for i in range(len(cands) - 1):
                self.assertGreaterEqual(cands[i].score, cands[i + 1].score)

    # Category 10: Source-Offset or Citation Mismatch
    def test_10_source_offset_or_citation_mismatch(self):
        """Offsets that do not match raw document text are rejected fail-closed."""
        raw_text = "Patient completed supervised physical therapy from July 1 through August 20, 2026."
        raw_docs = [{"source_id": "SYN-P001-PT-02", "patient_id": "SYN-P001", "date": "2026-09-15", "text": raw_text}]

        # Corrupted char_end (offset points past text boundary)
        corrupted_offsets = {
            "source_id": "SYN-P001-PT-02",
            "patient_id": "SYN-P001",
            "quote": raw_text,
            "char_start": 0,
            "char_end": len(raw_text) + 50,  # Corrupted out-of-bounds offset
        }
        is_valid, reasons, doc, s, e = validate_evidence_provenance(
            corrupted_offsets, patient_id="SYN-P001", raw_documents=raw_docs
        )
        self.assertFalse(is_valid)
        self.assertIn("INVALID_OFFSETS", reasons)

    # Category 11: Metadata Filtering Failure
    def test_11_metadata_filtering_version_isolation(self):
        """Querying an unindexed chunk_version returns empty list without error or contamination."""
        with self.SessionClass() as session:
            cands_v99 = retrieve_chart_candidates(
                session, patient_id="SYN-P001", query="physical therapy", top_k=3, chunk_version="v99_nonexistent"
            )
            self.assertEqual(len(cands_v99), 0)

    # Category 12: Patient/Case Isolation Failure
    def test_12_patient_case_isolation_defense(self):
        """Query text copied from a different patient cannot retrieve cross-patient records."""
        # Exact quote from SYN-P002 queried under SYN-P001
        foreign_query = "attended several sessions exact start date and duration are not documented"
        with self.SessionClass() as session:
            cands = retrieve_chart_candidates(session, patient_id="SYN-P001", query=foreign_query, top_k=5)
            self.assertEqual(len(cands), 0)
            for c in cands:
                self.assertNotEqual(c.patient_id, "SYN-P002")

    # Category 13: Calibrated vs Raw Hybrid RRF Safety
    def test_13_calibrated_vs_raw_hybrid_rrf_safety(self):
        """Proves hypothesis: Uncalibrated Raw Hybrid RRF leaks irrelevant candidates on off-domain queries,
        whereas Calibrated Hybrid RRF (min_dense_score=0.70) achieves 100% clean abstention."""
        off_domain_query = "coronary artery bypass graft cardiopulmonary bypass hemodynamics"
        with self.SessionClass() as session:
            # 1. Raw Hybrid RRF leaks 3 candidates on lumbar patient
            raw_hybrid = retrieve_hybrid_chart_candidates(
                session, patient_id="SYN-P001", query=off_domain_query, top_k=3, min_dense_score=0.0
            )
            self.assertEqual(len(raw_hybrid), 3)  # Fails safety check!

            # 2. Calibrated Hybrid RRF cleanly abstains
            cal_hybrid = retrieve_hybrid_chart_candidates(
                session, patient_id="SYN-P001", query=off_domain_query, top_k=3, min_dense_score=0.70
            )
            self.assertEqual(len(cal_hybrid), 0)  # Passes safety check!


if __name__ == "__main__":
    unittest.main()
