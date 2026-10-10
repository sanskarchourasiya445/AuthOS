"""Automated tests for Phase 7: Human Reviewer Interface and Workstation API Integration.

Verifies:
1. Frontend UI route serving (/ and /reviewer) with all 8 required screens.
2. Case and document listing with patient boundary isolation.
3. Raw document inspection and offset verification endpoints.
4. Cross-patient and cross-case authorization controls.
5. Reviewer criterion annotations with mandatory clinical notes.
6. Role-based determination permissions (clinician reviewer permitted, auditor denied).
7. Final adjudication workflow and packet finalization state transitions.
8. Advisory claim analysis vs authoritative verification immutability.
"""
import os
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.v1.cases import get_repository
from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.auth.security import create_access_token
from backend.db.models import AuditLogModel, CaseModel, CriterionResultModel, DocumentModel
from backend.db.repository import PostgresCaseRepository
from backend.db.seed import seed_synthetic_data
from backend.main import app
from backend.rag.ingest import ingest_synthetic_records
from contracts.schemas import CaseStatus, CriterionStatus, ErrorCode

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")


class Phase7ReviewerInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
        cls.SessionLocal = sessionmaker(bind=cls.engine)
        cls.repo = PostgresCaseRepository(session_factory=cls.SessionLocal)
        app.dependency_overrides[get_repository] = lambda: cls.repo

        cls.client = TestClient(app)

        with cls.SessionLocal() as session:
            seed_synthetic_data(session)
            ingest_synthetic_records(session, chunk_version="v1")
            session.commit()

        # Tokens
        cls.clinician_all_token = create_access_token(
            AuthenticatedUser(
                sub="REV-001",
                name="Dr. Sarah Chen, MD",
                role=UserRole.CLINICIAN_REVIEWER.value,
                cases=["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"],
            )
        )
        cls.clinician_c1_token = create_access_token(
            AuthenticatedUser(
                sub="REV-002",
                name="Dr. Allison Ross, MD",
                role=UserRole.CLINICIAN_REVIEWER.value,
                cases=["CASE-SYN-001"],
            )
        )
        cls.auditor_token = create_access_token(
            AuthenticatedUser(
                sub="AUD-001",
                name="Jane Doe (Auditor)",
                role=UserRole.AUDITOR.value,
                cases=["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"],
            )
        )

    def setUp(self):
        """Reset synthetic case states before each test method."""
        with self.SessionLocal() as session:
            for c in session.query(CaseModel).all():
                c.status = CaseStatus.RESULTS_READY.value
                c.finalized_at = None
                c.reviewer_note = None
            session.commit()

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    # =========================================================================
    # 1. UI ROUTE SERVING & 8 REQUIRED SCREENS MARKUP
    # =========================================================================

    def test_ui_serves_html_workstation(self):
        """Root / and /reviewer return 200 OK with the reviewer workstation HTML."""
        res_root = self.client.get("/")
        self.assertEqual(res_root.status_code, 200)
        self.assertIn("text/html", res_root.headers["content-type"])

        res_reviewer = self.client.get("/reviewer")
        self.assertEqual(res_reviewer.status_code, 200)
        self.assertEqual(res_root.text, res_reviewer.text)

    def test_ui_contains_all_8_required_screens_and_governance(self):
        """The single-page workstation contains markup for all 8 required clinical review views."""
        html = self.client.get("/").text

        # Screen 1: Authenticated sign-in modal & persona selection
        self.assertIn("modalSignIn", html)
        self.assertIn("loginAs", html)
        self.assertIn("dr_chen", html)
        self.assertIn("dr_ross", html)

        # Screen 2: Case list with queue and filter
        self.assertIn("screenQueue", html)
        self.assertIn("caseQueueBody", html)
        self.assertIn("queueStatusFilter", html)

        # Screen 3: Case workspace with patient document navigation
        self.assertIn("screenWorkspace", html)
        self.assertIn("wsPatientId", html)
        self.assertIn("wsService", html)
        self.assertIn("docListContainer", html)

        # Screen 4: Criterion review panel
        self.assertIn("wsCriteriaView", html)
        self.assertIn("criteriaListContainer", html)
        self.assertIn("submitCriterionAnnotation", html)

        # Screen 5: Source evidence viewer with offset highlighting
        self.assertIn("wsInspectorView", html)
        self.assertIn("docRawContent", html)
        self.assertIn("evidence-highlight", html)
        self.assertIn("loadDocumentDetail", html)

        # Screen 6: Advisory claim analysis vs authoritative verification diff
        self.assertIn("wsAdvisoryView", html)
        self.assertIn("comparisonContainer", html)
        self.assertIn("advisoryProviderLabel", html)

        # Screen 7: Human review and approval workflow
        self.assertIn("wsAdjudicateView", html)
        self.assertIn("finalActionSelect", html)
        self.assertIn("finalActionNote", html)
        self.assertIn("submitFinalDetermination", html)

        # Screen 8: Audit history and review packet view
        self.assertIn("wsAuditView", html)
        self.assertIn("packetSummaryBox", html)
        self.assertIn("auditTrailBody", html)

        # Safety & Governance checks
        self.assertIn("PRE-SUBMISSION EVIDENCE LINTER", html)
        self.assertIn("Deterministic Clinical Governance", html)

    # =========================================================================
    # 2. DOCUMENT NAVIGATION & PATIENT BOUNDARY ISOLATION
    # =========================================================================

    def test_list_case_documents_authorized(self):
        """Authorized reviewer can retrieve list of chart documents for a case."""
        headers = {"Authorization": f"Bearer {self.clinician_c1_token}"}
        res = self.client.get("/api/v1/cases/CASE-SYN-001/documents", headers=headers)
        self.assertEqual(res.status_code, 200)
        docs = res.json()
        self.assertIsInstance(docs, list)
        self.assertGreater(len(docs), 0)
        for d in docs:
            self.assertEqual(d["patient_id"], "SYN-P001")
            self.assertIn("source_id", d)
            self.assertIn("character_count", d)

    def test_list_case_documents_unauthorized_case_forbidden(self):
        """Reviewer not assigned to CASE-SYN-002 receives 403 Forbidden."""
        headers = {"Authorization": f"Bearer {self.clinician_c1_token}"}
        res = self.client.get("/api/v1/cases/CASE-SYN-002/documents", headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "ACCESS_DENIED")

    def test_get_document_detail_and_cross_patient_isolation(self):
        """Reviewer can fetch full raw text for authorized case, but cross-patient probe is blocked."""
        headers = {"Authorization": f"Bearer {self.clinician_c1_token}"}

        # 1. Fetch valid document for CASE-SYN-001 (SYN-P001)
        res = self.client.get("/api/v1/cases/CASE-SYN-001/documents/SYN-P001-NOTE-01", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["source_id"], "SYN-P001-NOTE-01")
        self.assertEqual(data["patient_id"], "SYN-P001")
        self.assertGreater(len(data["text"]), 0)

        # 2. Cross-patient isolation: Attempt to fetch SYN-P002 document via CASE-SYN-001 endpoint
        res_cross = self.client.get("/api/v1/cases/CASE-SYN-001/documents/SYN-P002-NOTE-01", headers=headers)
        self.assertEqual(res_cross.status_code, 403)
        self.assertEqual(res_cross.json()["error"]["code"], "ACCESS_DENIED")
        self.assertIn("does not belong to case patient", res_cross.json()["error"]["message"])

    # =========================================================================
    # 3. CRITERION REVIEW & ANNOTATION WORKFLOW
    # =========================================================================

    def test_criterion_review_annotation_requires_note(self):
        """Review action requires a non-empty clinical note."""
        headers = {"Authorization": f"Bearer {self.clinician_c1_token}"}

        # Empty note rejected
        res = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            json={"criterion_id": "C1", "action": "accept_gap", "note": "   "},
            headers=headers,
        )
        self.assertEqual(res.status_code, 422)

    def test_criterion_review_annotation_success_and_audited(self):
        """Clinician reviewer can annotate a criterion and action is committed to audit log."""
        headers = {"Authorization": f"Bearer {self.clinician_c1_token}"}
        note_text = "Clinician review confirms documented symptom history meets clinical intent."

        res = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            json={"criterion_id": "C1", "action": "accept_gap", "note": note_text},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["case_id"], "CASE-SYN-001")
        self.assertEqual(data["criterion_id"], "C1")
        self.assertEqual(data["action"], "accept_gap")

        # Verify audit trail record
        with self.SessionLocal() as session:
            audit = (
                session.query(AuditLogModel)
                .filter_by(case_id="CASE-SYN-001", criterion_id="C1", action="accept_gap")
                .order_by(AuditLogModel.created_at.desc())
                .first()
            )
            self.assertIsNotNone(audit)
            self.assertEqual(audit.note, note_text)
            self.assertIn("Dr. Allison Ross", audit.actor)

    def test_auditor_role_cannot_submit_review_action(self):
        """Auditor role receives 403 INSUFFICIENT_PERMISSIONS when attempting review annotation."""
        headers = {"Authorization": f"Bearer {self.auditor_token}"}
        res = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            json={"criterion_id": "C1", "action": "custom_note", "note": "Auditor comment"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "INSUFFICIENT_PERMISSIONS")

    # =========================================================================
    # 4. FINAL ADJUDICATION DESK & STATE TRANSITIONS
    # =========================================================================

    def test_final_adjudication_requires_clinical_rationale(self):
        """Final determination requires mandatory reviewer rationale."""
        headers = {"Authorization": f"Bearer {self.clinician_all_token}"}
        res = self.client.post(
            "/api/v1/cases/CASE-SYN-002/approve",
            json={"action": "request_edits", "reviewer_note": "   "},
            headers=headers,
        )
        self.assertEqual(res.status_code, 422)

    def test_auditor_role_cannot_finalize_packet(self):
        """Auditor role is forbidden from committing final adjudication."""
        headers = {"Authorization": f"Bearer {self.auditor_token}"}
        res = self.client.post(
            "/api/v1/cases/CASE-SYN-001/approve",
            json={"action": "approve_packet", "reviewer_note": "Auditor approval attempt"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "INSUFFICIENT_PERMISSIONS")

    def test_final_adjudication_transitions_packet_and_case_state(self):
        """Clinician final determination transitions packet to finalized and updates case status."""
        headers = {"Authorization": f"Bearer {self.clinician_all_token}"}

        # 1. APPROVE_PACKET on CASE-SYN-001
        approve_note = "All criteria substantiated; approved for MRI Lumbar Spine."
        res_app = self.client.post(
            "/api/v1/cases/CASE-SYN-001/approve",
            json={"action": "approve_packet", "reviewer_note": approve_note},
            headers=headers,
        )
        self.assertEqual(res_app.status_code, 200)
        packet_app = res_app.json()
        self.assertTrue(packet_app["finalized"])
        self.assertEqual(packet_app["reviewer_note"], approve_note)
        self.assertIsNotNone(packet_app["finalized_at"])

        with self.SessionLocal() as session:
            case1 = session.query(CaseModel).filter_by(case_id="CASE-SYN-001").first()
            self.assertEqual(case1.status, CaseStatus.FINALIZED.value)

            audit1 = (
                session.query(AuditLogModel)
                .filter_by(case_id="CASE-SYN-001", action="approve_packet")
                .order_by(AuditLogModel.id.desc())
                .first()
            )
            self.assertIsNotNone(audit1)
            self.assertIn("Dr. Sarah Chen", audit1.actor)

        # 2. REQUEST_EDITS on CASE-SYN-002
        edits_note = "Prior conservative trial incomplete; requesting additional physical therapy notes from specialist."
        res_edit = self.client.post(
            "/api/v1/cases/CASE-SYN-002/approve",
            json={"action": "request_edits", "reviewer_note": edits_note},
            headers=headers,
        )
        self.assertEqual(res_edit.status_code, 200)
        packet_edit = res_edit.json()
        # Edits requested means draft is not finalized yet
        self.assertFalse(packet_edit["finalized"])
        self.assertIn("EDITS_REQUESTED", packet_edit["reviewer_note"])

        with self.SessionLocal() as session:
            case2 = session.query(CaseModel).filter_by(case_id="CASE-SYN-002").first()
            self.assertEqual(case2.status, CaseStatus.IN_HUMAN_REVIEW.value)

            audit2 = (
                session.query(AuditLogModel)
                .filter_by(case_id="CASE-SYN-002", action="request_edits")
                .order_by(AuditLogModel.id.desc())
                .first()
            )
            self.assertIsNotNone(audit2)
            self.assertIn("Dr. Sarah Chen", audit2.actor)

    # =========================================================================
    # 5. ADVISORY ANALYSIS IMMUTABILITY
    # =========================================================================

    def test_advisory_analysis_returns_proposals_without_mutating_results(self):
        """Advisory AI analysis endpoint produces proposals but never overwrites authoritative results."""
        headers = {"Authorization": f"Bearer {self.clinician_all_token}"}

        with self.SessionLocal() as session:
            before_results = session.query(CriterionResultModel).filter_by(case_id="CASE-SYN-001").all()
            before_map = {r.criterion_id: (r.status, r.verified) for r in before_results}

        res = self.client.post("/api/v1/cases/CASE-SYN-001/claim-analysis", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("proposals", data)
        self.assertEqual(data["analyzer_provider"], "DETERMINISTIC_FALLBACK (RULE_BASED)")
        self.assertIn("advisory only", data["disclaimer"].lower())

        with self.SessionLocal() as session:
            after_results = session.query(CriterionResultModel).filter_by(case_id="CASE-SYN-001").all()
            after_map = {r.criterion_id: (r.status, r.verified) for r in after_results}
            self.assertEqual(before_map, after_map)


if __name__ == "__main__":
    unittest.main()
