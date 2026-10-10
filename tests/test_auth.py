"""Automated test suite for AuthOS authentication and authorization foundation.

Covers:
1. Missing credentials on protected endpoints -> 401 AUTHENTICATION_REQUIRED.
2. Malformed / non-Bearer credentials -> 401 AUTHENTICATION_REQUIRED or INVALID_TOKEN.
3. Tampered token signature -> 401 INVALID_TOKEN.
4. Expired token -> 401 TOKEN_EXPIRED.
5. Token issuance endpoint (/api/v1/auth/token) with valid and invalid credentials.
6. Profile introspection endpoint (/api/v1/auth/me).
7. Valid authenticated access for authorized cases.
8. Case-level authorization and cross-case denial (e.g. Dr. Ross allowed CASE-SYN-001, denied CASE-SYN-002) -> 403 ACCESS_DENIED.
9. Role-based authorization: Auditor role can inspect case/results/packets, but is denied /review and /approve -> 403 INSUFFICIENT_PERMISSIONS.
10. Correct authenticated actor identity persisted in AuditLogModel (replacing UNAUTHENTICATED_DEV).
11. Workflow state guards remain strictly enforced under authenticated callers (e.g. 409 INVALID_STATE_TRANSITION on double approval or draft review).
12. Production secret key validation guard.
"""
import os
import unittest
from datetime import timedelta
import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.auth.security import create_access_token
from backend.config import Settings, settings
from backend.db.models import (
    AuditLogModel,
    Base,
    CaseModel,
    CriterionResultModel,
    DocumentModel,
    PolicyCriterionModel,
    PolicyModel,
)
from backend.db.repository import PostgresCaseRepository
from backend.db.seed import seed_synthetic_data
from backend.main import create_app
from backend.api.v1.cases import get_repository
from contracts.schemas import (
    CaseStatus,
    ErrorCode,
    FinalizationActionType,
    ReviewActionType,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")
test_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


class AuthenticationAndAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    def setUp(self):
        with TestSession() as session:
            session.query(AuditLogModel).delete()
            session.query(CriterionResultModel).delete()
            session.query(CaseModel).delete()
            session.query(DocumentModel).delete()
            session.query(PolicyCriterionModel).delete()
            session.query(PolicyModel).delete()
            session.commit()
            seed_synthetic_data(session)
            session.commit()

        self.repo = PostgresCaseRepository(session_factory=TestSession)
        self.app = create_app()
        self.app.dependency_overrides[get_repository] = lambda: self.repo
        self.client = TestClient(self.app)

        # Helper tokens
        self.clinician_user = AuthenticatedUser(
            sub="REV-001",
            name="Dr. Sarah Chen, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"],
        )
        self.clinician_token = create_access_token(self.clinician_user)

        self.restricted_user = AuthenticatedUser(
            sub="REV-002",
            name="Dr. Allison Ross, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["CASE-SYN-001"],
        )
        self.restricted_token = create_access_token(self.restricted_user)

        self.auditor_user = AuthenticatedUser(
            sub="AUD-001",
            name="Jane Doe (Auditor)",
            role=UserRole.AUDITOR.value,
            cases=["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"],
        )
        self.auditor_token = create_access_token(self.auditor_user)

        self.admin_user = AuthenticatedUser(
            sub="ADM-001",
            name="Alex Rivera (Admin)",
            role=UserRole.ADMIN.value,
            cases=["*"],
        )
        self.admin_token = create_access_token(self.admin_user)

    # 1. Unauthenticated requests rejected on protected endpoints
    def test_unauthenticated_request_rejected_on_cases_list(self):
        resp = self.client.get("/api/v1/cases")
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body["error"]["code"], ErrorCode.AUTHENTICATION_REQUIRED.value)

    def test_unauthenticated_request_rejected_on_case_detail(self):
        resp = self.client.get("/api/v1/cases/CASE-SYN-001")
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body["error"]["code"], ErrorCode.AUTHENTICATION_REQUIRED.value)

    def test_unauthenticated_request_rejected_on_review(self):
        resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            json={
                "criterion_id": "C1",
                "action": ReviewActionType.CUSTOM_NOTE.value,
                "note": "Unauthenticated note.",
            },
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.AUTHENTICATION_REQUIRED.value)

    def test_unauthenticated_request_rejected_on_approval(self):
        resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/approve",
            json={
                "action": FinalizationActionType.APPROVE_PACKET.value,
                "reviewer_note": "Unauthenticated approval.",
            },
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.AUTHENTICATION_REQUIRED.value)

    def test_unauthenticated_request_rejected_on_evaluate(self):
        resp = self.client.post("/api/v1/cases/CASE-SYN-001/evaluate")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.AUTHENTICATION_REQUIRED.value)

    # 2. Public health check remains unauthenticated
    def test_health_check_remains_public(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    # 3. Token Issuance & Profile Introspection
    def test_token_issuance_valid_synthetic_credentials(self):
        payload = {
            "username": "dr_chen",
            "password": "synthetic-demo-pass-dr-chen",
        }
        resp = self.client.post("/api/v1/auth/token", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(data["user"]["sub"], "REV-001")
        self.assertEqual(data["user"]["role"], "clinician_reviewer")

    def test_token_issuance_invalid_credentials_rejected(self):
        payload = {
            "username": "dr_chen",
            "password": "wrong-password",
        }
        resp = self.client.post("/api/v1/auth/token", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.AUTHENTICATION_REQUIRED.value)

    def test_auth_me_returns_profile_for_authenticated_actor(self):
        resp = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {self.clinician_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["sub"], "REV-001")
        self.assertEqual(data["name"], "Dr. Sarah Chen, MD")
        self.assertEqual(data["role"], "clinician_reviewer")

    # 4. Token validation errors: malformed, tampered, expired
    def test_malformed_token_rejected(self):
        resp = self.client.get(
            "/api/v1/cases/CASE-SYN-001",
            headers={"Authorization": "Bearer not-a-valid-jwt-token"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.INVALID_TOKEN.value)

    def test_tampered_token_signature_rejected(self):
        tampered_token = self.clinician_token[:-6] + "xxxxxx"
        resp = self.client.get(
            "/api/v1/cases/CASE-SYN-001",
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.INVALID_TOKEN.value)

    def test_expired_token_rejected(self):
        expired_token = create_access_token(
            self.clinician_user,
            expires_delta=timedelta(seconds=-10),
        )
        resp = self.client.get(
            "/api/v1/cases/CASE-SYN-001",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.TOKEN_EXPIRED.value)

    # 5. Case-Level Authorization & Cross-Case Access Denial
    def test_cross_case_access_denied_for_restricted_user(self):
        # Dr. Ross has access ONLY to CASE-SYN-001
        # Accessing CASE-SYN-001 succeeds:
        ok_resp = self.client.get(
            "/api/v1/cases/CASE-SYN-001",
            headers={"Authorization": f"Bearer {self.restricted_token}"},
        )
        self.assertEqual(ok_resp.status_code, 200)

        # Attempting to read CASE-SYN-002 fails with 403 ACCESS_DENIED:
        cross_read = self.client.get(
            "/api/v1/cases/CASE-SYN-002",
            headers={"Authorization": f"Bearer {self.restricted_token}"},
        )
        self.assertEqual(cross_read.status_code, 403)
        self.assertEqual(cross_read.json()["error"]["code"], ErrorCode.ACCESS_DENIED.value)

        # Attempting to read results of CASE-SYN-002 fails with 403:
        cross_results = self.client.get(
            "/api/v1/cases/CASE-SYN-002/results",
            headers={"Authorization": f"Bearer {self.restricted_token}"},
        )
        self.assertEqual(cross_results.status_code, 403)
        self.assertEqual(cross_results.json()["error"]["code"], ErrorCode.ACCESS_DENIED.value)

        # Attempting to review CASE-SYN-002 fails with 403:
        cross_review = self.client.post(
            "/api/v1/cases/CASE-SYN-002/review",
            headers={"Authorization": f"Bearer {self.restricted_token}"},
            json={
                "criterion_id": "C1",
                "action": ReviewActionType.CUSTOM_NOTE.value,
                "note": "Cross-case attempt.",
            },
        )
        self.assertEqual(cross_review.status_code, 403)
        self.assertEqual(cross_review.json()["error"]["code"], ErrorCode.ACCESS_DENIED.value)

        # Attempting to approve CASE-SYN-002 fails with 403:
        cross_approve = self.client.post(
            "/api/v1/cases/CASE-SYN-002/approve",
            headers={"Authorization": f"Bearer {self.restricted_token}"},
            json={
                "action": FinalizationActionType.APPROVE_PACKET.value,
                "reviewer_note": "Cross-case approve attempt.",
            },
        )
        self.assertEqual(cross_approve.status_code, 403)
        self.assertEqual(cross_approve.json()["error"]["code"], ErrorCode.ACCESS_DENIED.value)

    def test_cases_list_filters_to_assigned_cases_for_restricted_user(self):
        resp = self.client.get(
            "/api/v1/cases",
            headers={"Authorization": f"Bearer {self.restricted_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        cases = resp.json()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["case_id"], "CASE-SYN-001")

    # 6. Role-Based Permissions (Auditor cannot review or finalize)
    def test_auditor_can_inspect_case_and_results(self):
        resp_case = self.client.get(
            "/api/v1/cases/CASE-SYN-001",
            headers={"Authorization": f"Bearer {self.auditor_token}"},
        )
        self.assertEqual(resp_case.status_code, 200)

        resp_results = self.client.get(
            "/api/v1/cases/CASE-SYN-001/results",
            headers={"Authorization": f"Bearer {self.auditor_token}"},
        )
        self.assertEqual(resp_results.status_code, 200)

    def test_auditor_denied_review_action(self):
        resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            headers={"Authorization": f"Bearer {self.auditor_token}"},
            json={
                "criterion_id": "C1",
                "action": ReviewActionType.CUSTOM_NOTE.value,
                "note": "Auditor trying to add clinical review note.",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.INSUFFICIENT_PERMISSIONS.value)

    def test_auditor_denied_approval_action(self):
        resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/approve",
            headers={"Authorization": f"Bearer {self.auditor_token}"},
            json={
                "action": FinalizationActionType.APPROVE_PACKET.value,
                "reviewer_note": "Auditor trying to approve packet.",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.INSUFFICIENT_PERMISSIONS.value)

    # 7. Authenticated Actor Identity Persisted in Audit Logs
    def test_review_action_records_authenticated_actor_identity(self):
        resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            headers={"Authorization": f"Bearer {self.clinician_token}"},
            json={
                "criterion_id": "C1",
                "action": ReviewActionType.CUSTOM_NOTE.value,
                "note": "Documenting 10 weeks of physical therapy completed.",
            },
        )
        self.assertEqual(resp.status_code, 200)

        # Inspect database audit log directly
        with TestSession() as session:
            audit = (
                session.query(AuditLogModel)
                .filter_by(case_id="CASE-SYN-001", action=ReviewActionType.CUSTOM_NOTE.value)
                .first()
            )
            self.assertIsNotNone(audit)
            self.assertEqual(audit.actor, "Dr. Sarah Chen, MD (REV-001)")
            self.assertNotIn("UNAUTHENTICATED_DEV", audit.actor)

    def test_approval_action_records_authenticated_actor_identity(self):
        resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/approve",
            headers={"Authorization": f"Bearer {self.clinician_token}"},
            json={
                "action": FinalizationActionType.APPROVE_PACKET.value,
                "reviewer_note": "Approved based on clinical evidence compliance.",
            },
        )
        self.assertEqual(resp.status_code, 200)

        with TestSession() as session:
            audit = (
                session.query(AuditLogModel)
                .filter_by(case_id="CASE-SYN-001", action="approve_packet")
                .first()
            )
            self.assertIsNotNone(audit)
            self.assertEqual(audit.actor, "Dr. Sarah Chen, MD (REV-001)")
            self.assertNotIn("UNAUTHENTICATED_DEV", audit.actor)

    # 8. Workflow state guards remain enforced with valid authentication
    def test_workflow_state_guards_intact_under_authentication(self):
        # Put case into DRAFT state
        with TestSession() as session:
            case = session.query(CaseModel).filter_by(case_id="CASE-SYN-001").first()
            case.status = CaseStatus.DRAFT.value
            session.commit()

        # Review action on DRAFT must fail with 409 INVALID_STATE_TRANSITION
        review_resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/review",
            headers={"Authorization": f"Bearer {self.clinician_token}"},
            json={
                "criterion_id": "C1",
                "action": ReviewActionType.CUSTOM_NOTE.value,
                "note": "Cannot review un-evaluated case.",
            },
        )
        self.assertEqual(review_resp.status_code, 409)
        self.assertEqual(review_resp.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

        # Approval on DRAFT must fail with 409 INVALID_STATE_TRANSITION
        approve_resp = self.client.post(
            "/api/v1/cases/CASE-SYN-001/approve",
            headers={"Authorization": f"Bearer {self.clinician_token}"},
            json={
                "action": FinalizationActionType.APPROVE_PACKET.value,
                "reviewer_note": "Cannot approve draft case.",
            },
        )
        self.assertEqual(approve_resp.status_code, 409)
        self.assertEqual(approve_resp.json()["error"]["code"], ErrorCode.INVALID_STATE_TRANSITION.value)

    # 9. Startup Configuration Validation
    def test_production_configuration_rejects_insecure_default_secret(self):
        bad_settings = Settings(
            app_env="production",
            auth_secret_key="dev-insecure-secret-key-change-in-production-authos-2026",
        )
        with self.assertRaises(ValueError) as ctx:
            bad_settings.validate_production_configuration()
        self.assertIn("Insecure default AUTHOS_SECRET_KEY", str(ctx.exception))

    def test_production_configuration_rejects_short_secret(self):
        bad_settings = Settings(
            app_env="production",
            auth_secret_key="too-short-secret",
        )
        with self.assertRaises(ValueError) as ctx:
            bad_settings.validate_production_configuration()
        self.assertIn("at least 32 bytes", str(ctx.exception))

    def test_production_configuration_accepts_strong_secret(self):
        good_settings = Settings(
            app_env="production",
            auth_secret_key="a" * 32,
        )
        # Should not raise
        good_settings.validate_production_configuration()


if __name__ == "__main__":
    unittest.main()
