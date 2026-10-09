"""AuthOS application configuration."""
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
    max_retrieval_retries: int = 2
    database_url: str = "postgresql+psycopg2://authos@localhost:5433/authos"

    # Authentication & Security
    auth_secret_key: str = "dev-insecure-secret-key-change-in-production-authos-2026"
    auth_algorithm: str = "HS256"
    auth_token_expire_minutes: int = 120
    auth_issuer: str = "authos"

    def validate_production_configuration(self) -> None:
        """Enforce strict production security invariants."""
        if self.app_env.lower() in ("production", "prod"):
            if self.auth_secret_key == "dev-insecure-secret-key-change-in-production-authos-2026":
                raise ValueError("Insecure default AUTHOS_SECRET_KEY cannot be used in production.")
            if len(self.auth_secret_key.encode("utf-8")) < 32:
                raise ValueError("AUTHOS_SECRET_KEY must be at least 32 bytes in production.")


settings = Settings()
settings.validate_production_configuration()
