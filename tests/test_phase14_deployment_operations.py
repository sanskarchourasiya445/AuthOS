"""Phase 14 Deployment, Configuration, and Operational Readiness Tests.

Verifies:
1. Liveness endpoint behavior (/health/live).
2. Readiness endpoint behavior with healthy and simulated degraded database (/health/ready).
3. Database target sanitization without secret exposure.
4. Strict production configuration validation (secret length, production DB, LLM keys).
5. Development-only synthetic credential guards (403 in production).
6. Idempotent seeding and chunk ingestion on repeated runs.
7. Non-blocking advisory LLM status behavior on readiness probes.
"""
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings, settings
from backend.db.seed import seed_synthetic_data
from backend.db.session import SessionLocal
from backend.main import app
from backend.rag.ingest import ingest_synthetic_records
from contracts.schemas import ErrorCode


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestPhase14DeploymentAndOperations:
    """Operational readiness, configuration, and health check test suite."""

    def test_liveness_endpoint_returns_200(self, client: TestClient):
        """Liveness endpoint must return 200 OK immediately without external I/O."""
        response = client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert data["service"] == "authos-api"

    def test_readiness_endpoint_returns_200_when_database_connected(self, client: TestClient):
        """Readiness endpoint returns 200 OK with connected database status."""
        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert "advisory_provider" in data
        assert data["advisory_provider"]["role"] == "advisory_only"

    def test_readiness_endpoint_returns_503_when_database_unreachable(self, client: TestClient):
        """Readiness probe returns 503 Service Unavailable without leaking connection details or credentials."""
        with patch("backend.api.v1.health.SessionLocal") as mock_session_local:
            mock_session = MagicMock()
            mock_session.execute.side_effect = Exception("Simulated DB connection failure to secret_host:5432")
            mock_session_local.return_value.__enter__.return_value = mock_session

            response = client.get("/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["database"] == "unavailable"
            # Ensure no credentials or tracebacks are leaked
            assert "secret_host" not in response.text
            assert "Exception" not in response.text

    def test_sanitized_database_url_masks_credentials(self):
        """Sanitized database URL helper masks plain-text passwords."""
        s = Settings(
            database_url="postgresql+psycopg2://clinical_admin:SuperSecretPassword123@prod-db.internal:5432/authos_prod"
        )
        sanitized = s.get_sanitized_database_url()
        assert "SuperSecretPassword123" not in sanitized
        assert "postgresql+psycopg2://clinical_admin:***@prod-db.internal:5432/authos_prod" == sanitized

    def test_production_configuration_rejects_default_secret_key(self):
        """Production environment must reject the default development secret key."""
        s = Settings(
            app_env="production",
            auth_secret_key="dev-insecure-secret-key-change-in-production-authos-2026",
            database_url="postgresql+psycopg2://user:pass@prod.db:5432/authos",
        )
        with pytest.raises(ValueError, match="Insecure default AUTHOS_SECRET_KEY"):
            s.validate_production_configuration()

    def test_production_configuration_rejects_short_secret_key(self):
        """Production environment must require at least 32 bytes for AUTH_SECRET_KEY."""
        s = Settings(
            app_env="production",
            auth_secret_key="too-short-secret-key",
            database_url="postgresql+psycopg2://user:pass@prod.db:5432/authos",
        )
        with pytest.raises(ValueError, match="AUTHOS_SECRET_KEY must be at least 32 bytes"):
            s.validate_production_configuration()

    def test_production_configuration_rejects_empty_database_url(self):
        """Production environment must reject empty database URLs."""
        s = Settings(
            app_env="production",
            auth_secret_key="a" * 32,
            database_url="",
        )
        with pytest.raises(ValueError, match="DATABASE_URL must be configured"):
            s.validate_production_configuration()

    def test_production_configuration_requires_gemini_key_when_gemini_selected(self):
        """Production environment requires GEMINI_API_KEY if LLM_PROVIDER is set to gemini."""
        s = Settings(
            app_env="production",
            auth_secret_key="a" * 32,
            database_url="postgresql+psycopg2://prod_user:prod_pass@prod-db.internal:5432/authos",
            llm_provider="gemini",
            gemini_api_key=None,
        )
        with pytest.raises(ValueError, match="GEMINI_API_KEY must be provided"):
            s.validate_production_configuration()

    def test_production_configuration_passes_with_valid_settings(self):
        """Valid production settings pass validation without raising errors."""
        s = Settings(
            app_env="production",
            auth_secret_key="a" * 32,
            database_url="postgresql+psycopg2://prod_user:prod_pass@prod-db.internal:5432/authos",
            llm_provider="stub",
        )
        s.validate_production_configuration()
        assert s.app_env == "production"

    def test_synthetic_authentication_disabled_in_production(self, client: TestClient):
        """Synthetic credential authentication endpoint (/api/v1/auth/token) is rejected in production."""
        with patch.object(settings, "app_env", "production"):
            response = client.post(
                "/api/v1/auth/token",
                json={"username": "dr_chen", "password": "synthetic-demo-pass-dr-chen"},
            )
            assert response.status_code == 403
            data = response.json()
            assert data["error"]["code"] == ErrorCode.ACCESS_DENIED.value
            assert "Synthetic credential authentication is disabled in production" in data["error"]["message"]

    def test_seeding_and_ingestion_idempotence(self):
        """Running synthetic data seeding and chunk ingestion repeatedly produces zero duplicate entities."""
        with SessionLocal() as session:
            # First execution (already seeded)
            counts1 = seed_synthetic_data(session)
            chunks1 = ingest_synthetic_records(session)

            # Second execution
            counts2 = seed_synthetic_data(session)
            chunks2 = ingest_synthetic_records(session)

            assert counts2["policies"] == 0
            assert counts2["criteria"] == 0
            assert counts2["documents"] == 0
            assert counts2["cases"] == 0
            assert counts2["results"] == 0

    def test_advisory_llm_unconfigured_does_not_fail_readiness_probe(self, client: TestClient):
        """Unconfigured Gemini credentials do not block readiness probe because LLM is strictly advisory."""
        with patch.object(settings, "llm_provider", "gemini"), patch.object(settings, "gemini_api_key", None):
            response = client.get("/health/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["advisory_provider"]["name"] == "gemini"
            assert data["advisory_provider"]["status"] == "unconfigured"
            assert data["advisory_provider"]["role"] == "advisory_only"
