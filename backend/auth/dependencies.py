"""FastAPI dependency providers for authentication and authorization guards."""
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.auth.security import (
    InvalidTokenError,
    TokenExpiredError,
    decode_access_token,
)
from contracts.schemas import ErrorCode

http_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Bearer token authentication via signed JWT",
)


def get_current_user(
    auth: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer_scheme)],
) -> AuthenticatedUser:
    """Extract, decode, and validate the Bearer JWT token from the Authorization header."""
    if not auth or not auth.credentials or auth.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": ErrorCode.AUTHENTICATION_REQUIRED.value,
                "message": "Authentication required. Bearer token missing.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(auth.credentials)
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": ErrorCode.TOKEN_EXPIRED.value,
                "message": "Authentication token has expired.",
            },
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"token_expired\""},
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": ErrorCode.INVALID_TOKEN.value,
                "message": f"Invalid authentication token: {exc}",
            },
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        ) from exc

    return AuthenticatedUser(
        sub=payload.sub,
        name=payload.name,
        role=payload.role,
        cases=payload.cases,
    )


def require_case_access(
    case_id: Annotated[str, Path(description="Case identifier to authorize")],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """Authorize actor access to the specific case ID."""
    if user.role == UserRole.ADMIN.value or "*" in user.cases or case_id in user.cases:
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": ErrorCode.ACCESS_DENIED.value,
            "message": f"Actor '{user.sub}' is not authorized to access case '{case_id}'.",
        },
    )


def require_reviewer_role(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """Ensure actor possesses clinician reviewer or administrative privileges."""
    if user.role in (UserRole.CLINICIAN_REVIEWER.value, UserRole.ADMIN.value):
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": ErrorCode.INSUFFICIENT_PERMISSIONS.value,
            "message": f"Actor with role '{user.role}' lacks clinician reviewer permissions.",
        },
    )
