"""Tests for AuthOS Phase 15 Model Context Protocol (MCP) Server.

Verifies:
1. Tool registry exposes only authorized read-only tools (no mutations, approvals, or SQL execution).
2. Authentication fails closed when credentials are missing or invalid.
3. Strict case-level authorization prevents unauthorized access across users.
4. Cross-patient chart isolation prevents reading foreign patient documents.
5. Deterministic evidence linting returns valid statuses and character offsets.
6. Document excerpt slicing validates verbatim text and character boundaries.
"""
import contextlib
import io
import json
import logging
import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import patch

from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.auth.security import create_access_token
from backend.config import settings
from backend.db.models import CaseModel, DocumentModel
from backend.db.seed import seed_synthetic_data
from backend.db.session import SessionLocal
from backend.mcp.auth import (
    MCPAccessDeniedError,
    MCPAuthenticationError,
    get_authenticated_actor,
    verify_actor_case_access,
)
from backend.mcp.server import (
    authos_get_case,
    authos_get_document_excerpt,
    authos_lint_evidence,
    authos_list_cases,
    server,
)
from contracts.schemas import CaseStatus, CriterionStatus


class TestPhase15MCPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SessionLocal() as session:
            seed_synthetic_data(session)
            session.commit()

        # Generate tokens for testing
        cls.user_chen = AuthenticatedUser(
            sub="REV-001",
            name="Dr. Sarah Chen, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"],
        )
        cls.token_chen = create_access_token(cls.user_chen)

        # Restricted reviewer: only authorized for CASE-SYN-001
        cls.user_ross = AuthenticatedUser(
            sub="REV-002",
            name="Dr. Allison Ross, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["CASE-SYN-001"],
        )
        cls.token_ross = create_access_token(cls.user_ross)

    def test_01_tool_registry_read_only_boundary(self):
        """Verify that server only registers approved read-only tools and zero mutation tools."""
        registered_tools = [t.name for t in server._tool_manager.list_tools()]
        expected_tools = {
            "authos_list_cases",
            "authos_get_case",
            "authos_lint_evidence",
            "authos_get_document_excerpt",
        }
        self.assertEqual(set(registered_tools), expected_tools)

        # Confirm no approval, finalization, modification, or SQL tools exist
        prohibited_terms = ["approve", "finalize", "delete", "update", "sql", "mutate", "execute"]
        for tool_name in registered_tools:
            for term in prohibited_terms:
                self.assertNotIn(term, tool_name.lower())

    def test_02_missing_auth_fails_closed(self):
        """Tools reject unauthenticated requests when no token or default actor is supplied."""
        with patch.dict(os.environ, {}, clear=True):
            res_raw = authos_list_cases(auth_token=None)
            res = json.loads(res_raw)
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_code"], "AUTHENTICATION_REQUIRED")

            res_case = json.loads(authos_get_case("CASE-SYN-001", auth_token=None))
            self.assertEqual(res_case["status"], "error")
            self.assertEqual(res_case["error_code"], "AUTHENTICATION_REQUIRED")

            res_lint = json.loads(authos_lint_evidence("CASE-SYN-001", auth_token=None))
            self.assertEqual(res_lint["status"], "error")
            self.assertEqual(res_lint["error_code"], "AUTHENTICATION_REQUIRED")

    def test_03_invalid_or_malformed_token_rejected(self):
        """Tampered or invalid JWT strings are strictly rejected."""
        res = json.loads(authos_list_cases(auth_token="malformed.jwt.token"))
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_code"], "AUTHENTICATION_REQUIRED")

    def test_04_actor_scoped_case_listing(self):
        """Restricted reviewer sees only assigned cases; full reviewer sees all."""
        # Dr. Ross is restricted to CASE-SYN-001
        res_ross = json.loads(authos_list_cases(auth_token=self.token_ross))
        self.assertEqual(res_ross["status"], "success")
        case_ids_ross = [c["case_id"] for c in res_ross["cases"]]
        self.assertEqual(case_ids_ross, ["CASE-SYN-001"])

        # Dr. Chen has access to all 3 synthetic cases
        res_chen = json.loads(authos_list_cases(auth_token=self.token_chen))
        self.assertEqual(res_chen["status"], "success")
        case_ids_chen = [c["case_id"] for c in res_chen["cases"]]
        self.assertTrue(set(case_ids_chen).issuperset({"CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"}))

    def test_05_cross_case_access_denied_for_restricted_user(self):
        """Restricted reviewer cannot retrieve details or lint an unauthorized case."""
        # CASE-SYN-002 access attempt by Dr. Ross (unauthorized)
        res_get = json.loads(authos_get_case("CASE-SYN-002", auth_token=self.token_ross))
        self.assertEqual(res_get["status"], "error")
        self.assertEqual(res_get["error_code"], "ACCESS_DENIED")
        self.assertIn("REV-002", res_get["message"])

        # Linting attempt on unauthorized case
        res_lint = json.loads(authos_lint_evidence("CASE-SYN-002", auth_token=self.token_ross))
        self.assertEqual(res_lint["status"], "error")
        self.assertEqual(res_lint["error_code"], "ACCESS_DENIED")

    def test_06_cross_patient_document_access_denied(self):
        """Attempting to access a document belonging to another patient via a valid case fails."""
        # Dr. Chen is authorized for CASE-SYN-001 (patient SYN-P001), but attempts to fetch SYN-P002-NOTE-01
        res = json.loads(
            authos_get_document_excerpt(
                case_id="CASE-SYN-001",
                source_id="SYN-P002-NOTE-01",  # Belongs to SYN-P002
                auth_token=self.token_chen,
            )
        )
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_code"], "CROSS_PATIENT_ACCESS_DENIED")
        self.assertIn("does not belong to patient", res["message"])

    def test_07_deterministic_evidence_linting_output(self):
        """authos_lint_evidence produces authoritative results without LLM decision authority."""
        res = json.loads(authos_lint_evidence("CASE-SYN-001", auth_token=self.token_chen))
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["case_id"], "CASE-SYN-001")
        self.assertEqual(res["patient_id"], "SYN-P001")
        self.assertEqual(res["verification_mode"], "DETERMINISTIC_RULES_ENGINE")

        # Verify criteria results structure and valid statuses
        allowed_statuses = {"MET", "MISSING", "AMBIGUOUS", "CONTRADICTED"}
        criteria = res["criteria_results"]
        self.assertGreater(len(criteria), 0)
        for cr in criteria:
            self.assertIn(cr["status"], allowed_statuses)
            self.assertIsInstance(cr["verified"], bool)
            self.assertIn("missing_facts", cr)
            for ev in cr["evidence_citations"]:
                self.assertIn("source_id", ev)
                self.assertIn("quote", ev)
                self.assertIsNotNone(ev["char_start"])
                self.assertIsNotNone(ev["char_end"])

    def test_08_document_excerpt_exact_slice_verification(self):
        """authos_get_document_excerpt returns exact verbatim slice and flags invalid offsets."""
        # 1. Valid offset slice
        res = json.loads(
            authos_get_document_excerpt(
                case_id="CASE-SYN-001",
                source_id="SYN-P001-NOTE-01",
                char_start=0,
                char_end=40,
                auth_token=self.token_chen,
            )
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["source_id"], "SYN-P001-NOTE-01")
        self.assertEqual(len(res["excerpt"]), 40)
        self.assertTrue(res["verified_verbatim"])

        # 2. Out-of-bounds offset rejected
        res_bad = json.loads(
            authos_get_document_excerpt(
                case_id="CASE-SYN-001",
                source_id="SYN-P001-NOTE-01",
                char_start=0,
                char_end=99999,
                auth_token=self.token_chen,
            )
        )
        self.assertEqual(res_bad["status"], "error")
        self.assertEqual(res_bad["error_code"], "INVALID_OFFSETS")

    def test_09_default_actor_blocked_in_production_mode(self):
        """Default synthetic actor fallback is strictly disabled in production/staging environments."""
        with patch.dict(os.environ, {"AUTHOS_MCP_DEFAULT_ACTOR": "dr_chen"}), patch.object(
            settings, "app_env", "production"
        ):
            res = json.loads(authos_list_cases(auth_token=None))
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_code"], "AUTHENTICATION_REQUIRED")
            self.assertIn("disabled in environment 'production'", res["message"])

    def test_10_explicit_empty_token_fails_closed(self):
        """Explicit empty or whitespace token fails closed immediately without falling back to ambient credentials."""
        with patch.dict(os.environ, {"AUTHOS_MCP_TOKEN": self.token_chen, "AUTHOS_MCP_DEFAULT_ACTOR": "dr_chen"}):
            # Empty string
            res_empty = json.loads(authos_list_cases(auth_token=""))
            self.assertEqual(res_empty["status"], "error")
            self.assertEqual(res_empty["error_code"], "AUTHENTICATION_REQUIRED")
            self.assertIn("empty", res_empty["message"].lower())

            # Whitespace-only string
            res_ws = json.loads(authos_list_cases(auth_token="   \t\n  "))
            self.assertEqual(res_ws["status"], "error")
            self.assertEqual(res_ws["error_code"], "AUTHENTICATION_REQUIRED")
            self.assertIn("empty", res_ws["message"].lower())

    def test_11_expired_token_rejected_in_mcp(self):
        """Expired JWT token is safely rejected with AUTHENTICATION_REQUIRED."""
        expired_token = create_access_token(self.user_chen, expires_delta=timedelta(seconds=-60))
        res = json.loads(authos_list_cases(auth_token=expired_token))
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_code"], "AUTHENTICATION_REQUIRED")
        self.assertIn("expired", res["message"].lower())

    def test_12_stdio_logging_isolated_to_stderr(self):
        """Diagnostic logging from MCP subsystem routes strictly to stderr, keeping stdout clean for JSON-RPC."""
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            mcp_logger = logging.getLogger("authos.mcp.server")
            mcp_logger.warning("Test diagnostic warning for stdio transport verification")

        self.assertEqual(buf_out.getvalue(), "", "sys.stdout must remain strictly empty for JSON-RPC transport")
        self.assertIn("Test diagnostic warning for stdio transport verification", buf_err.getvalue())


if __name__ == "__main__":
    unittest.main()
