"""AuthOS FastAPI application entry point."""
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.v1.router import api_v1_router
from backend.config import settings
from contracts.schemas import ErrorCode, ErrorDetail, ErrorEnvelope


def create_app() -> FastAPI:
    """Application factory for AuthOS API."""
    app = FastAPI(
        title="AuthOS API",
        description="Evidence-grounded prior-authorization preparation system.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Standardize 422 validation errors to ErrorEnvelope."""
        error_messages = "; ".join(f"{err['loc'][-1]}: {err['msg']}" for err in exc.errors())
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Validation failed: {error_messages}",
            )
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=envelope.model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Standardize HTTPExceptions to ErrorEnvelope when detail is a structured dict or message."""
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            envelope = ErrorEnvelope(
                error=ErrorDetail(
                    code=exc.detail["code"],
                    message=exc.detail.get("message", "An error occurred."),
                )
            )
        else:
            code = ErrorCode.INTERNAL_ERROR
            if exc.status_code == 404:
                code = ErrorCode.CASE_NOT_FOUND
            envelope = ErrorEnvelope(
                error=ErrorDetail(
                    code=code,
                    message=str(exc.detail),
                )
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope.model_dump(),
        )

    app.include_router(api_v1_router, prefix=settings.api_prefix)
    return app


app = create_app()
