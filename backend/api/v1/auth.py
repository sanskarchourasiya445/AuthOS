"""Authentication endpoints for token acquisition and profile verification."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.auth.dependencies import get_current_user
from backend.auth.schemas import (
    AuthenticatedUser,
    TokenRequest,
    TokenResponse,
)
from backend.auth.security import (
    authenticate_synthetic_user,
    create_access_token,
)
from backend.config import settings
from contracts.schemas import ErrorCode

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post(
    "/token",
    summary="Obtain JWT access token using synthetic credentials",
    response_model=TokenResponse,
)
def login_for_access_token(credentials: TokenRequest) -> TokenResponse:
    """Issue a signed JWT access token for synthetic reviewer/auditor accounts."""
    user = authenticate_synthetic_user(credentials.username, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": ErrorCode.AUTHENTICATION_REQUIRED.value,
                "message": "Invalid username or password.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.auth_token_expire_minutes * 60,
        user=user,
    )


@auth_router.get(
    "/me",
    summary="Get current authenticated actor identity",
    response_model=AuthenticatedUser,
)
def get_current_actor(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """Return profile and permissions of the currently authenticated actor."""
    return current_user
