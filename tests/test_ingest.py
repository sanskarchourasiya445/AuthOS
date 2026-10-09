"""Unit and integration tests for deterministic document ingestion and text chunking."""
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
from backend.rag.ingest import (
    chunk_canonical_policy_json,
    chunk_patient_document,
    chunk_policy_document,
    estimate_tokens,
    ingest_synthetic_records,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class ChunkingAlgorithmUnitTests(unittest.TestCase):
    """Pure unit tests for deterministic chunking boundaries and offset guarantees."""

    def test_token_estimator(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("   "), 0)
        tokens = estimate_tokens("Patient completed 6 weeks of physical therapy.")
        self.assertGreater(tokens, 5)

    def test_exact_source_text_preservation_offsets(self):
        text = (
            "Paragraph one: Patient reports low back pain.\n\n"
            "Paragraph two: Conservative therapy started on July 1.\n\n"
            "Paragraph three: Follow up shows persistent radicular symptoms."
        )
        chunks = chunk_patient_document(
            source_id="DOC-001",
            patient_id="SYN-P001",
            text=text,
            doc_date="2026-07-01",
            target_tokens=10,
            max_tokens=20,
        )
        self.assertGreater(len(chunks), 1)
        for chk in chunks:
            # Non-negotiable provenance invariant: exact slice matches chunk_text
            self.assertEqual(text[chk.char_start:chk.char_end], chk.chunk_text)
            self.assertEqual(chk.patient_id, "SYN-P001")
            self.assertEqual(chk.source_id, "DOC-001")
            self.assertEqual(chk.doc_date, "2026-07-01")

    def test_policy_heading_and_section_boundaries(self):
        policy_md = (
            "# Lumbar MRI Coverage Guidelines\n"
            "## Section 1: Clinical Indications\n"
            "Low back pain must be documented for at least six weeks.\n\n"
            "## Section 2: Conservative Treatment Requirements\n"
            "Patient must complete at least six weeks of physical therapy or supervised rehab.\n\n"
            "## Section 3: Clinician Orders\n"
            "A formal dated imaging order must be present."
        )
        chunks = chunk_policy_document(
            policy_id="POL-001",
            text=policy_md,
            target_tokens=20,
            max_tokens=50,
        )
        self.assertGreaterEqual(len(chunks), 3)
        headings = [c.heading for c in chunks if c.heading]
        self.assertTrue(any("Section 1" in h for h in headings))
        self.assertTrue(any("Section 2" in h for h in headings))
        self.assertTrue(any("Section 3" in h for h in headings))
        for c in chunks:
            self.assertEqual(policy_md[c.char_start:c.char_end], c.chunk_text)

    def test_long_paragraph_sub_chunking_on_sentences(self):
        # Create a single paragraph with 50 repetitive sentences
        long_para = " ".join([f"Sentence {i} documents persistent low back pain." for i in range(50)])
        self.assertGreater(estimate_tokens(long_para), 300)

        chunks = chunk_patient_document(
            source_id="DOC-LONG",
            patient_id="SYN-P001",
            text=long_para,
            target_tokens=50,
            max_tokens=100,
        )
        self.assertGreater(len(chunks), 1)
        for chk in chunks:
            self.assertEqual(long_para[chk.char_start:chk.char_end], chk.chunk_text)
            self.assertLessEqual(chk.token_count, 120)

    def test_empty_and_whitespace_documents(self):
        self.assertEqual(chunk_patient_document(source_id="D1", patient_id="P1", text=""), [])
        self.assertEqual(chunk_patient_document(source_id="D1", patient_id="P1", text="   \n\n\t  "), [])
        self.assertEqual(chunk_policy_document(policy_id="POL-1", text=""), [])

    def test_missing_date_handled_gracefully(self):
        chunks = chunk_patient_document(
            source_id="D2",
            patient_id="P2",
            text="Single note without date.",
            doc_date=None,
        )
        self.assertEqual(len(chunks), 1)
        self.assertIsNone(chunks[0].doc_date)

    def test_stable_chunk_ids_and_ordering(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks_run1 = chunk_patient_document(source_id="D3", patient_id="P3", text=text, target_tokens=5)
        chunks_run2 = chunk_patient_document(source_id="D3", patient_id="P3", text=text, target_tokens=5)

        self.assertEqual(len(chunks_run1), len(chunks_run2))
        for c1, c2 in zip(chunks_run1, chunks_run2):
            self.assertEqual(c1.chunk_id, c2.chunk_id)
            self.assertEqual(c1.chunk_index, c2.chunk_index)
            self.assertEqual(c1.char_start, c2.char_start)
            self.assertEqual(c1.char_end, c2.char_end)


class IngestionPersistenceIntegrationTests(unittest.TestCase):
    """Integration tests verifying PostgreSQL storage and idempotent ingestion."""

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
            session.commit()

    def test_ingest_synthetic_records_persists_chunks(self):
        with self.SessionClass() as session:
            counts = ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

            self.assertGreater(counts["policy_chunks"], 0)
            self.assertGreater(counts["document_chunks"], 0)

            # Verify in PostgreSQL
            p_chunks = session.query(PolicyChunkModel).all()
            d_chunks = session.query(DocumentChunkModel).all()
            self.assertEqual(len(p_chunks), counts["policy_chunks"])
            self.assertEqual(len(d_chunks), counts["document_chunks"])

            # Verify provenance fields
            for dc in d_chunks:
                self.assertIsNotNone(dc.source_id)
                self.assertIsNotNone(dc.patient_id)
                self.assertIsNotNone(dc.chunk_text)
                self.assertEqual(dc.chunk_version, "v1")

    def test_re_ingestion_idempotency(self):
        with self.SessionClass() as session:
            # First ingestion
            ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

            # Second ingestion on same version
            counts_reingest = ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

            # Zero new chunks created on repeat
            self.assertEqual(counts_reingest["policy_chunks"], 0)
            self.assertEqual(counts_reingest["document_chunks"], 0)

    def test_foreign_key_cascade_deletion(self):
        with self.SessionClass() as session:
            ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

            doc = session.query(DocumentModel).first()
            source_id = doc.source_id
            chunks_before = session.query(DocumentChunkModel).filter_by(source_id=source_id).count()
            self.assertGreater(chunks_before, 0)

            # Delete the parent document
            session.delete(doc)
            session.commit()

            # Chunks must be deleted via cascade
            chunks_after = session.query(DocumentChunkModel).filter_by(source_id=source_id).count()
            self.assertEqual(chunks_after, 0)

    def test_stale_chunks_purged_on_reingestion(self):
        with self.SessionClass() as session:
            ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

            # Insert an artificial extra chunk for SYN-P001-NOTE-01 with a high index
            extra_chunk = DocumentChunkModel(
                chunk_id="SYN-P001-NOTE-01_chk999_v1",
                source_id="SYN-P001-NOTE-01",
                patient_id="SYN-P001",
                chunk_text="Old stale content from earlier document version.",
                chunk_index=999,
                char_start=0,
                char_end=48,
                token_count=8,
                chunk_version="v1",
            )
            session.add(extra_chunk)
            session.commit()

            self.assertIsNotNone(
                session.query(DocumentChunkModel).filter_by(chunk_id="SYN-P001-NOTE-01_chk999_v1").first()
            )

            # Re-ingest synthetic records
            ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

            # The stale chunk must be deleted
            self.assertIsNone(
                session.query(DocumentChunkModel).filter_by(chunk_id="SYN-P001-NOTE-01_chk999_v1").first()
            )

    def test_transaction_rollback_on_ingestion_error(self):
        with self.SessionClass() as session:
            # Trigger an integrity error by attempting an invalid insert
            try:
                with session.begin_nested():
                    invalid_chunk = DocumentChunkModel(
                        chunk_id="INVALID_CHUNK",
                        source_id="NON_EXISTENT_SOURCE_ID",  # Violates foreign key
                        patient_id="SYN-P999",
                        chunk_text="Orphan chunk",
                        chunk_index=0,
                        char_start=0,
                        char_end=12,
                        token_count=2,
                        chunk_version="v1",
                    )
                    session.add(invalid_chunk)
                    session.flush()
            except Exception:
                pass  # nested transaction rolled back

            # Verify session state is intact and invalid chunk is not present
            self.assertIsNone(
                session.query(DocumentChunkModel).filter_by(chunk_id="INVALID_CHUNK").first()
            )


if __name__ == "__main__":
    unittest.main()
