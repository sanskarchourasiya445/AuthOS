"""End-to-end browser tests for AuthOS Phase 9 React + TypeScript Reviewer Workstation.

Verifies against the live React production build served on /app:
1. Open the React application.
2. Sign in with authorized synthetic test identity (Dr. Sarah Chen, MD).
3. Open an authorized case (CASE-SYN-001).
4. Inspect its source documents and navigate from a criterion citation to exact quoted passage.
5. Inspect proposed and verified results in Advisory vs Authoritative diff.
6. Exercise an allowed human-review action / finalization.
7. Inspect the review packet and confirm immutable audit trail logging.
8. Verify that an unauthorized case is rejected for a restricted persona (Dr. Allison Ross).
9. Log out and verify session behavior.
"""
import os
import socket
import threading
import time
import unittest

from playwright.sync_api import sync_playwright
import uvicorn

from backend.db.models import CaseModel
from backend.db.seed import seed_synthetic_data
from backend.db.session import SessionLocal
from backend.main import app
from backend.rag.ingest import ingest_synthetic_records
from contracts.schemas import CaseStatus


def find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Phase9ReactBrowserE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Seed database
        with SessionLocal() as session:
            seed_synthetic_data(session)
            ingest_synthetic_records(session, chunk_version="v1")
            for c in session.query(CaseModel).all():
                c.status = CaseStatus.RESULTS_READY.value
                c.finalized_at = None
                c.reviewer_note = None
            session.commit()

        # 2. Spin up live FastAPI server on free port
        cls.port = find_free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error")
        cls.server = uvicorn.Server(config)
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.server_thread.start()

        # Allow server to start listening
        for _ in range(30):
            try:
                s = socket.socket()
                s.connect(("127.0.0.1", cls.port))
                s.close()
                break
            except OSError:
                time.sleep(0.1)

        # 3. Launch headless browser
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="msedge", headless=True)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.playwright.stop()
        except Exception:
            pass
        cls.server.should_exit = True

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 850})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def test_01_full_clinical_review_workflow_in_react(self):
        """End-to-end clinical reviewer workflow on the React workstation."""
        # Step 1: Open the React application
        self.page.goto(f"{self.base_url}/app")
        self.page.wait_for_selector(".brand-title")
        self.assertIn("AuthOS", self.page.text_content(".brand-title"))
        self.assertIn("PRE-SUBMISSION EVIDENCE LINTER", self.page.text_content(".brand-badge"))

        # Step 2: Authenticate as Dr. Sarah Chen, MD
        self.page.wait_for_selector("#userChip")
        # Ensure authenticated
        actor_name = self.page.text_content("#actorName")
        if "Dr. Sarah Chen" not in actor_name:
            self.page.click("#btnSwitchActor")
            self.page.wait_for_selector(".persona-btn")
            self.page.locator(".persona-btn").filter(has_text="Dr. Sarah Chen, MD").click()
            self.page.wait_for_selector("#actorName:has-text('Dr. Sarah Chen, MD')")

        # Step 3: Open Case Queue and select CASE-SYN-001
        self.page.wait_for_selector("#screenQueue")
        self.page.wait_for_selector("text=CASE-SYN-001")
        # Click Open Workspace for CASE-SYN-001
        row = self.page.locator("tr", has_text="CASE-SYN-001")
        row.locator("button:has-text('Open Workspace')").click()

        # Step 4: Verify Case Workspace
        self.page.wait_for_selector("#screenWorkspace")
        self.page.wait_for_selector("#wsCaseId:has-text('CASE-SYN-001')")
        self.page.wait_for_selector("#wsPatientId:has-text('SYN-P001')")

        # Step 5: Navigate from Criterion citation to Source Document Inspector
        self.page.wait_for_selector("#criteriaListContainer")
        inspect_btn = self.page.locator("button:has-text('🔍 Inspect in Source')").first
        inspect_btn.click()

        # Confirm subtab switched to Source Document Inspector
        self.page.wait_for_selector("#wsInspectorView")
        self.page.wait_for_selector("#activeHighlightSpan")
        highlighted_text = self.page.text_content("#activeHighlightSpan")
        self.assertGreater(len(highlighted_text), 5)
        # Verify verified badge
        self.page.wait_for_selector("#docVerificationStatus:has-text('Verified')")

        # Step 6: Test Advisory vs Authoritative Diff
        self.page.click("#wsTabAdvisory")
        self.page.wait_for_selector("#wsAdvisoryView")
        self.page.wait_for_selector("#btnRunAgentWorkflow")
        self.page.click("#btnRunAgentWorkflow")
        # Wait for advisory results
        self.page.wait_for_selector("#comparisonContainer .comparison-grid")
        self.assertIn("Authoritative Verification", self.page.text_content("#comparisonContainer"))
        self.assertIn("Advisory Proposal", self.page.text_content("#comparisonContainer"))

        # Step 7: Clinician Adjudication & Approval
        self.page.click("#wsTabAdjudicate")
        self.page.wait_for_selector("#wsAdjudicateView")
        # Enter clinical note
        self.page.fill("#finalActionNote", "Clinically verified based on documented 8-week physical therapy chart notes.")
        self.page.click("#btnSubmitFinal")
        # Verify success toast
        self.page.wait_for_selector(".toast-success:has-text('Final determination recorded')")

        # Step 8: Final Review Packet & Immutable Audit History
        self.page.click("#wsTabAudit")
        self.page.wait_for_selector("#wsAuditView")
        self.page.wait_for_selector("#packetSummaryBox:has-text('FINALIZED')")
        self.page.wait_for_selector("#auditTrailBody tr")
        self.assertIn("Dr. Sarah Chen, MD", self.page.text_content("#auditTrailBody"))

        # Step 9: Switch persona to Dr. Allison Ross (restricted to CASE-SYN-001 only)
        self.page.click("#btnSwitchActor")
        self.page.wait_for_selector(".persona-btn")
        self.page.locator(".persona-btn").filter(has_text="Dr. Allison Ross, MD").click()
        self.page.wait_for_selector("#actorName:has-text('Dr. Allison Ross, MD')")

        # Go to Case Queue
        self.page.click("#tabQueue")
        self.page.wait_for_selector("#screenQueue")

        # Dr. Ross should only have access to CASE-SYN-001 in queue
        self.page.wait_for_selector("text=CASE-SYN-001")
        # CASE-SYN-002 should NOT be in the table for Dr. Ross
        case_2_count = self.page.locator("tr", has_text="CASE-SYN-002").count()
        self.assertEqual(case_2_count, 0)

        # Step 10: Sign Out
        self.page.click("#btnLogout")
        self.page.wait_for_selector("#actorName:has-text('Unauthenticated')")
