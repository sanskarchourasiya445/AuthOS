"""Health, liveness, and readiness endpoints for AuthOS operations."""
import logging
from typing import Any
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from backend.config import settings
from backend.db.session import SessionLocal

logger = logging.getLogger("authos.health")
health_router = APIRouter(tags=["health"])


@health_router.get("/health/live", summary="Lightweight liveness probe")
def liveness_check() -> dict[str, str]:
    """Fast probe indicating the process is running and accepting HTTP requests."""
    return {"status": "alive", "service": "authos-api"}


@health_router.get("/health/ready", summary="Dependency readiness probe")
def readiness_check(response: Response) -> dict[str, Any]:
    """Readiness probe checking database connectivity and reporting advisory provider status.
    
    Returns 200 OK when database is accessible and ready to serve traffic.
    Returns 503 Service Unavailable when the database is unreachable.
    Does not leak connection credentials, query internals, or stack traces.
    """
    db_ready = False
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        db_ready = True
    except Exception as exc:
        logger.warning("Readiness probe database check failed: %s", type(exc).__name__)
        db_ready = False

    # Advisory LLM provider status check (optional / non-blocking for readiness)
    if settings.llm_provider == "gemini":
        advisory_status = "ready" if settings.gemini_api_key else "unconfigured"
        advisory_mode = "hosted_llm"
    else:
        advisory_status = "ready"
        advisory_mode = "offline_deterministic"

    advisory_info = {
        "name": settings.llm_provider,
        "status": advisory_status,
        "mode": advisory_mode,
        "role": "advisory_only",
    }

    if not db_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "database": "unavailable",
            "advisory_provider": advisory_info,
        }

    return {
        "status": "ready",
        "database": "connected",
        "advisory_provider": advisory_info,
    }


@health_router.get("/api/v1/health", summary="Legacy API health check")
def legacy_health_check() -> dict[str, str]:
    """Backwards-compatible health endpoint."""
    return {"status": "ok", "version": "v1"}
