"""AuthOS application configuration."""
import re
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration parsed from environment variables."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_prefix: str = "/api/v1"
    enable_corrective_retrieval: bool = False
    max_retrieval_retries: int = Field(default=2, ge=0, le=5, description="Maximum number of corrective retrieval retries")
    database_url: str = "postgresql+psycopg2://authos@localhost:5433/authos"

    # Authentication & Security
    auth_secret_key: str = "dev-insecure-secret-key-change-in-production-authos-2026"
    auth_algorithm: str = "HS256"
    auth_token_expire_minutes: int = 120
    auth_issuer: str = "authos"
    auth_audience: str = "authos-api"

    # LLM Provider & Evaluation (Phase 11)
    llm_provider: str = Field(default="stub", description="LLM provider identifier: 'stub' or 'gemini'")
    llm_model: str = Field(default="gemini-3.5-flash-lite", description="LLM model identifier")
    gemini_api_key: str | None = Field(default=None, description="Google Gemini API key")
    llm_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0, description="LLM request timeout in seconds")
    llm_max_retries: int = Field(default=2, ge=0, le=5, description="Maximum number of LLM provider retries")

    def get_sanitized_database_url(self) -> str:
        """Return database URL with masked password for safe logging and status reporting."""
        return re.sub(r"://([^:@]+):([^@]+)@", r"://\1:***@", self.database_url)

    def validate_production_configuration(self) -> None:
        """Enforce strict production security invariants."""
        if self.app_env.lower() in ("production", "prod"):
            if self.auth_secret_key == "dev-insecure-secret-key-change-in-production-authos-2026":
                raise ValueError("Insecure default AUTHOS_SECRET_KEY cannot be used in production.")
            if len(self.auth_secret_key.encode("utf-8")) < 32:
                raise ValueError("AUTHOS_SECRET_KEY must be at least 32 bytes in production.")
            if not self.database_url:
                raise ValueError("DATABASE_URL must be configured for a production database instance.")
            if self.llm_provider == "gemini" and not self.gemini_api_key:
                raise ValueError("GEMINI_API_KEY must be provided when LLM_PROVIDER is configured to 'gemini' in production.")


settings = Settings()
settings.validate_production_configuration()
