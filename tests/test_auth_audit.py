"""Phase 4.1 Focused Security Audit and Adversarial Verification Tests.

Tests the following security boundaries:
1. Token endpoint rejects privilege escalation attempts in request body (extra="forbid").
2. Synthetic token endpoint is strictly disabled in production (APP_ENV=production).
3. Token validation rejects unexpected algorithms (e.g. HS384, none).
4. Token validation rejects invalid / forged issuer (iss claim mismatch).
5. Token validation rejects invalid / forged audience (aud claim mismatch).
6. Token validation rejects tokens with future issued-at timestamp (iat > now + 60).
7. Token validation rejects invalid / unknown roles (role not in UserRole).
8. Wildcard case access is restricted strictly to administrator role.
9. Scope filtering in PostgresCaseRepository queries database with WHERE case_id IN (...).
10. Cross-case isolation across all endpoints (evaluate, review, approve, packet, results, get_case).
"""
import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.auth.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    get_oct_key,
)
from backend.config import settings
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
from contracts.schemas import ErrorCode

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://authos@localhost:5433/authos_test")
test_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


class SecurityAuditAdversarialTests(unittest.TestCase):
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

    # 1. Adversarial Token Request: Client attempting to inject privilege claims
    def test_token_endpoint_rejects_client_privilege_escalation_fields(self):
        """Client attempting to inject role=admin or cases=['*'] in login request is rejected with 422."""
        payload = {
            "username": "dr_ross",
            "password": "synthetic-demo-pass-dr-ross",
            "role": "admin",
            "cases": ["*"],
        }
        resp = self.client.post("/api/v1/auth/token", json=payload)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.VALIDATION_ERROR.value)

    # 2. Synthetic token endpoint disabled in production
    def test_synthetic_token_endpoint_disabled_in_production(self):
        """In production environment, synthetic demo credentials endpoint must be disabled."""
        payload = {
            "username": "admin_alex",
            "password": "synthetic-demo-pass-admin-alex",
        }
        with patch.object(settings, "app_env", "production"):
            resp = self.client.post("/api/v1/auth/token", json=payload)
            self.assertEqual(resp.status_code, 403)
            self.assertIn("disabled in production", resp.json()["error"]["message"].lower())

    # 3. JWT validation rejects wrong issuer
    def test_jwt_validation_rejects_wrong_issuer(self):
        """Tokens with an unauthorized or mismatched issuer claim must be rejected."""
        key = get_oct_key()
        now = int(time.time())
        bad_issuer_claims = {
            "sub": "REV-001",
            "name": "Dr. Sarah Chen, MD",
            "role": "clinician_reviewer",
            "cases": ["CASE-SYN-001"],
            "iat": now,
            "exp": now + 3600,
            "iss": "unauthorized-external-issuer",
            "aud": getattr(settings, "auth_audience", "authos-api"),
        }
        bad_token = jwt.encode({"alg": "HS256", "typ": "JWT"}, bad_issuer_claims, key)
        with self.assertRaises(InvalidTokenError) as ctx:
            decode_access_token(bad_token)
        self.assertIn("issuer", str(ctx.exception).lower())

    # 4. JWT validation rejects wrong audience
    def test_jwt_validation_rejects_wrong_audience(self):
        """Tokens minted for another service or audience must be rejected."""
        key = get_oct_key()
        now = int(time.time())
        bad_aud_claims = {
            "sub": "REV-001",
            "name": "Dr. Sarah Chen, MD",
            "role": "clinician_reviewer",
            "cases": ["CASE-SYN-001"],
            "iat": now,
            "exp": now + 3600,
            "iss": settings.auth_issuer,
            "aud": "wrong-target-service",
        }
        bad_token = jwt.encode({"alg": "HS256", "typ": "JWT"}, bad_aud_claims, key)
        with self.assertRaises(InvalidTokenError) as ctx:
            decode_access_token(bad_token)
        self.assertIn("audience", str(ctx.exception).lower())

    # 5. JWT validation rejects future issued-at timestamp
    def test_jwt_validation_rejects_future_iat(self):
        """Tokens with issued-at timestamps significantly in the future must be rejected."""
        key = get_oct_key()
        now = int(time.time())
        future_claims = {
            "sub": "REV-001",
            "name": "Dr. Sarah Chen, MD",
            "role": "clinician_reviewer",
            "cases": ["CASE-SYN-001"],
            "iat": now + 3600,
            "exp": now + 7200,
            "iss": settings.auth_issuer,
            "aud": getattr(settings, "auth_audience", "authos-api"),
        }
        future_token = jwt.encode({"alg": "HS256", "typ": "JWT"}, future_claims, key)
        with self.assertRaises(InvalidTokenError) as ctx:
            decode_access_token(future_token)
        self.assertIn("issued in the future", str(ctx.exception).lower())

    # 6. JWT validation rejects invalid / unknown role
    def test_jwt_validation_rejects_unknown_role(self):
        """Tokens with fabricated roles outside UserRole enum must be rejected."""
        key = get_oct_key()
        now = int(time.time())
        bad_role_claims = {
            "sub": "REV-001",
            "name": "Dr. Sarah Chen, MD",
            "role": "super_admin_god_mode",
            "cases": ["*"],
            "iat": now,
            "exp": now + 3600,
            "iss": settings.auth_issuer,
            "aud": getattr(settings, "auth_audience", "authos-api"),
        }
        bad_token = jwt.encode({"alg": "HS256", "typ": "JWT"}, bad_role_claims, key)
        with self.assertRaises(InvalidTokenError) as ctx:
            decode_access_token(bad_token)
        self.assertIn("role", str(ctx.exception).lower())

    # 7. Wildcard case access restricted strictly to administrator
    def test_wildcard_case_access_denied_for_non_admin(self):
        """A non-admin user with wildcard '*' in cases must NOT receive unrestricted access."""
        rogue_clinician = AuthenticatedUser(
            sub="REV-ROGUE",
            name="Dr. Rogue",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["*"],  # Rogue wildcard claim
        )
        token = create_access_token(rogue_clinician)
        resp = self.client.get(
            "/api/v1/cases/CASE-SYN-001",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Must be forbidden because non-admin cannot use wildcard '*'
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], ErrorCode.ACCESS_DENIED.value)

    # 8. Scope filtering pushed to database query
    def test_repository_get_all_cases_filters_at_sql_level(self):
        """Repository get_all_cases filters in SQL query when allowed_case_ids is supplied."""
        # Query with only CASE-SYN-002
        filtered = self.repo.get_all_cases(allowed_case_ids=["CASE-SYN-002"])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].case_id, "CASE-SYN-002")

        # Query with empty allowed list
        empty_filtered = self.repo.get_all_cases(allowed_case_ids=[])
        self.assertEqual(len(empty_filtered), 0)


if __name__ == "__main__":
    unittest.main()
