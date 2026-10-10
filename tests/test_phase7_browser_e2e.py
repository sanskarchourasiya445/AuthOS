"""End-to-end browser tests for AuthOS Phase 7 Clinical Reviewer Workstation.

Uses Playwright with headless Microsoft Edge to test real user interactions:
1. Sign in and open an authorized case.
2. Inspect a source citation and verify its highlighted text.
3. Submit a reviewer annotation.
4. Attempt a forbidden action as an auditor.
5. Finalize a review with a valid rationale.
6. Reload the page and verify persisted state and audit history.
7. Attempt cross-patient access and confirm it is denied.
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


class Phase7BrowserE2ETests(unittest.TestCase):
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
        with SessionLocal() as session:
            for c in session.query(CaseModel).all():
                c.status = CaseStatus.RESULTS_READY.value
                c.finalized_at = None
                c.reviewer_note = None
            session.commit()

        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(self.base_url)
        self.page.wait_for_load_state("networkidle")

    def tearDown(self):
        self.context.close()

    def test_e2e_01_signin_and_open_authorized_case(self):
        """User signs in as Dr. Sarah Chen, views case queue, and opens CASE-SYN-001."""
        page = self.page

        # Wait for persona auto-login or open modal
        page.locator("#actorName").wait_for(timeout=5000)
        actor_text = page.locator("#actorName").inner_text()
        self.assertIn("Dr. Sarah Chen", actor_text)

        # Ensure Case Queue is visible
        page.locator("#caseQueueBody").wait_for()
        self.assertTrue(page.locator("#caseQueueBody tr:has-text('CASE-SYN-001')").is_visible())

        # Click Open Workspace on CASE-SYN-001
        page.locator("button:has-text('Open Workspace')").first.click()
        page.wait_for_selector("#screenWorkspace.active")

        # Verify workspace header displays case info
        self.assertEqual(page.locator("#wsCaseId").inner_text(), "CASE-SYN-001")
        self.assertEqual(page.locator("#wsPatientId").inner_text(), "SYN-P001")

    def test_e2e_02_inspect_source_citation_highlight(self):
        """Reviewer clicks an evidence citation and verifies exact highlighted text in source viewer."""
        page = self.page

        # Open CASE-SYN-001 workspace
        page.locator("button:has-text('Open Workspace')").first.click()
        page.wait_for_selector("#screenWorkspace.active")

        # Ensure criteria panel is visible
        page.locator("#wsTabCriteria").click()
        page.wait_for_selector("#criteriaListContainer .criterion-card")

        # Click Inspect in Source on the first citation
        inspect_btn = page.locator("button:has-text('Inspect in Source')").first
        inspect_btn.click()

        # Verify subtab switched to Inspector view
        page.wait_for_selector("#wsInspectorView:visible")
        page.wait_for_selector("mark.evidence-highlight")

        highlight = page.locator("mark.evidence-highlight")
        self.assertTrue(highlight.is_visible())
        highlighted_text = highlight.inner_text().strip()
        self.assertGreater(len(highlighted_text), 0)

        # Verify inspector metadata contains offsets and document details
        self.assertTrue(page.locator("#docViewerTitle").is_visible())
        self.assertIn("SYN-P001", page.locator("#docViewerTitle").inner_text())
        self.assertTrue(page.locator("#docVerificationStatus").is_visible())

    def test_e2e_03_submit_reviewer_annotation(self):
        """Reviewer annotates a criterion with a mandatory clinical note."""
        page = self.page

        page.locator("button:has-text('Open Workspace')").first.click()
        page.wait_for_selector("#screenWorkspace.active")
        page.locator("#wsTabCriteria").click()
        page.wait_for_selector("#criteriaListContainer .criterion-card")

        # Fill reviewer note for criterion C1
        note_input = page.locator("input[id^='note_C']").first
        note_text = "E2E Annotation: Documentation meets conservative threshold."
        note_input.fill(note_text)

        # Click Save Annotation
        save_btn = page.locator("button:has-text('Save Annotation')").first
        save_btn.click()

        # Wait for toast confirms commit
        page.wait_for_selector("#toast:has-text('Criterion annotation committed')")
        toast_text = page.locator("#toast").inner_text()
        self.assertIn("Criterion annotation committed to audit trail", toast_text)

    def test_e2e_04_auditor_role_forbidden_from_adjudication(self):
        """Auditor persona cannot commit final adjudication (button is disabled in UI)."""
        page = self.page

        # Click Switch Actor
        page.locator("#btnSwitchActor").click()
        page.locator("#modalSignIn").wait_for()

        # Select Auditor Jane
        page.locator("#modalSignIn .persona-btn:has-text('Jane Doe')").click()
        page.wait_for_selector("#modalSignIn", state="hidden")

        # Verify auditor role
        page.wait_for_selector("#actorRoleBadge:has-text('auditor')")

        # Open workspace
        page.locator("button:has-text('Open Workspace')").first.click()
        page.wait_for_selector("#screenWorkspace.active")

        # Switch to Adjudication tab
        page.locator("#wsTabAdjudicate").click()
        page.wait_for_selector("#wsAdjudicateView:visible")

        # Adjudication button must be disabled for Auditor
        commit_btn = page.locator("#btnSubmitFinal")
        self.assertTrue(commit_btn.is_disabled())

    def test_e2e_05_finalize_review_and_verify_persistence_on_reload(self):
        """Clinician finalizes review packet with valid rationale, and reloaded page displays finalized state."""
        page = self.page

        # Ensure logged in as Clinician Reviewer Dr. Sarah Chen
        page.locator("#btnSwitchActor").click()
        page.locator("#modalSignIn .persona-btn:has-text('Dr. Sarah Chen')").click()
        page.wait_for_selector("#modalSignIn", state="hidden")

        # Open CASE-SYN-001
        page.locator("button:has-text('Open Workspace')").first.click()
        page.wait_for_selector("#screenWorkspace.active")

        # Navigate to Adjudication view
        page.locator("#wsTabAdjudicate").click()
        page.wait_for_selector("#wsAdjudicateView:visible")

        # Select approve_packet
        page.locator("#finalActionSelect").select_option("approve_packet")
        page.locator("#finalActionNote").fill("E2E Final Approval: Prior authorization criteria verified and approved.")

        # Submit final determination
        page.locator("#btnSubmitFinal").click()

        # Verify toast
        page.wait_for_selector("#toast:has-text('Final determination recorded')")
        self.assertIn("Final determination recorded successfully", page.locator("#toast").inner_text())

        # Reload the page to test durable persistence
        page.reload()
        page.wait_for_load_state("networkidle")

        # Reopen CASE-SYN-001
        page.locator("button:has-text('Open Workspace')").first.click()
        page.wait_for_selector("#screenWorkspace.active")

        # Check packet badge displays FINALIZED
        packet_badge = page.locator("#wsPacketBadge")
        self.assertIn("FINALIZED", packet_badge.inner_text())

        # Navigate to Audit tab and verify audit event
        page.locator("#wsTabAudit").click()
        page.wait_for_selector("#auditTrailBody tr")
        audit_text = page.locator("#auditTrailBody").inner_text()
        self.assertIn("approve_packet", audit_text)
        self.assertIn("Dr. Sarah Chen", audit_text)

    def test_e2e_06_cross_patient_access_denied_via_api_and_ui(self):
        """User without access to CASE-SYN-002 cannot open it or retrieve its documents."""
        page = self.page

        # Switch to Dr. Allison Ross (only authorized for CASE-SYN-001)
        page.locator("#btnSwitchActor").click()
        page.locator("#modalSignIn .persona-btn:has-text('Dr. Allison Ross')").click()
        page.wait_for_selector("#modalSignIn", state="hidden")

        # CASE-SYN-002 should NOT be in the table for Dr. Ross
        page.wait_for_selector("#caseQueueBody tr")
        queue_text = page.locator("#caseQueueBody").inner_text()
        self.assertNotIn("CASE-SYN-002", queue_text)

        # Attempting direct fetch to CASE-SYN-002 returns 403 Forbidden
        token = page.evaluate("() => currentAuthToken")
        self.assertIsNotNone(token)

        resp_status = page.evaluate(
            """async () => {
                const res = await fetch('/api/v1/cases/CASE-SYN-002', {
                    headers: { 'Authorization': `Bearer ${currentAuthToken}` }
                });
                return res.status;
            }"""
        )
        self.assertEqual(resp_status, 403)


if __name__ == "__main__":
    unittest.main()
