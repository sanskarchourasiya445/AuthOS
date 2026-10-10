"""Authentication and authorization scoping for AuthOS MCP server."""
import os
import logging
from backend.auth.schemas import AuthenticatedUser, UserRole
from backend.auth.security import (
    _SYNTHETIC_USERS,
    InvalidTokenError,
    TokenExpiredError,
    decode_access_token,
)
from backend.config import settings

logger = logging.getLogger("authos.mcp.auth")

_SUPPORTED_LOCAL_ENVS = {"development", "dev", "test", "testing", "local"}


class MCPAuthenticationError(PermissionError):
    """Raised when an MCP caller fails authentication."""


class MCPAccessDeniedError(PermissionError):
    """Raised when an MCP caller attempts to access an unauthorized case or document."""


def get_authenticated_actor(auth_token: str | None = None) -> AuthenticatedUser:
    """Resolve and validate the actor calling the MCP tool.

    Precedence:
    1. Explicit `auth_token` argument passed into the tool call.
       - If explicitly supplied but empty or whitespace, fails closed immediately.
    2. Ambient `AUTHOS_MCP_TOKEN` environment variable.
    3. Ambient `AUTHOS_MCP_DEFAULT_ACTOR` (e.g. 'dr_chen', 'dr_ross') for local development/testing only.
    4. If none provided or invalid, fails closed.
    """
    # 1. Explicit token argument
    if auth_token is not None:
        token = auth_token.strip()
        if not token:
            raise MCPAuthenticationError("Provided authentication token is empty.")
    else:
        # 2. Ambient environment token
        raw_env_token = os.getenv("AUTHOS_MCP_TOKEN")
        token = raw_env_token.strip() if raw_env_token else None

    if token:
        try:
            payload = decode_access_token(token)
            role_val = payload.role.value if isinstance(payload.role, UserRole) else str(payload.role)
            return AuthenticatedUser(
                sub=payload.sub,
                name=payload.name,
                role=role_val,
                cases=payload.cases,
            )
        except TokenExpiredError as exc:
            raise MCPAuthenticationError("Authentication token has expired.") from exc
        except InvalidTokenError as exc:
            raise MCPAuthenticationError(f"Invalid authentication token: {exc}") from exc
        except Exception as exc:
            raise MCPAuthenticationError(f"Token decoding failed: {exc}") from exc

    # 3. Local synthetic fallback for testing / development only
    default_actor_key = os.getenv("AUTHOS_MCP_DEFAULT_ACTOR")
    if default_actor_key:
        current_env = (settings.app_env or "").lower()
        if current_env not in _SUPPORTED_LOCAL_ENVS:
            raise MCPAuthenticationError(
                f"Default synthetic actor fallback is disabled in environment '{settings.app_env}'. "
                "A valid JWT auth_token or AUTHOS_MCP_TOKEN is required."
            )
        if default_actor_key in _SYNTHETIC_USERS:
            return _SYNTHETIC_USERS[default_actor_key]["user"]
        raise MCPAuthenticationError(
            f"Unknown synthetic actor '{default_actor_key}'. Valid actors: {', '.join(_SYNTHETIC_USERS.keys())}"
        )

    # 4. Fail closed
    raise MCPAuthenticationError(
        "Authentication required: Provide a valid JWT auth_token argument, "
        "set AUTHOS_MCP_TOKEN, or set AUTHOS_MCP_DEFAULT_ACTOR for local testing."
    )


def verify_actor_case_access(actor: AuthenticatedUser, case_id: str) -> None:
    """Enforce strict actor-to-case scoping.

    Admins have wildcard access. Other roles require explicit assignment in `actor.cases`.
    """
    if not case_id or not isinstance(case_id, str):
        raise MCPAccessDeniedError("Invalid or missing case_id.")

    if actor.role == UserRole.ADMIN.value:
        return

    if case_id in actor.cases:
        return

    raise MCPAccessDeniedError(
        f"Access Denied: Actor '{actor.sub}' ({actor.name}) is not authorized to access case '{case_id}'."
    )
