"""Cryptographic token issuing, decoding, and synthetic user authentication."""
import secrets
import time
from datetime import timedelta
from typing import Any

from joserfc import jwt
from joserfc.jwk import OctKey
from joserfc.errors import BadSignatureError, DecodeError

from backend.auth.schemas import AuthenticatedUser, TokenPayload, UserRole
from backend.config import settings


class AuthSecurityError(Exception):
    """Base exception for authentication errors."""


class InvalidTokenError(AuthSecurityError):
    """Raised when a token signature is invalid, malformed, or tampered."""


class TokenExpiredError(AuthSecurityError):
    """Raised when a token timestamp has passed."""


# Pre-configured synthetic user identities for local development and deterministic tests.
# Real credentials must never be hardcoded or used with this system.
_SYNTHETIC_USERS: dict[str, dict[str, Any]] = {
    "dr_chen": {
        "password": "synthetic-demo-pass-dr-chen",
        "user": AuthenticatedUser(
            sub="REV-001",
            name="Dr. Sarah Chen, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"],
        ),
    },
    "dr_ross": {
        "password": "synthetic-demo-pass-dr-ross",
        "user": AuthenticatedUser(
            sub="REV-002",
            name="Dr. Allison Ross, MD",
            role=UserRole.CLINICIAN_REVIEWER.value,
            cases=["CASE-SYN-001"],
        ),
    },
    "auditor_jane": {
        "password": "synthetic-demo-pass-auditor-jane",
        "user": AuthenticatedUser(
            sub="AUD-001",
            name="Jane Doe (Auditor)",
            role=UserRole.AUDITOR.value,
            cases=["CASE-SYN-001", "CASE-SYN-002", "CASE-SYN-003"],
        ),
    },
    "admin_alex": {
        "password": "synthetic-demo-pass-admin-alex",
        "user": AuthenticatedUser(
            sub="ADM-001",
            name="Alex Rivera (Admin)",
            role=UserRole.ADMIN.value,
            cases=["*"],
        ),
    },
}


def get_oct_key() -> OctKey:
    """Import HMAC OctKey from configured secret key."""
    return OctKey.import_key(settings.auth_secret_key.encode("utf-8"))


def create_access_token(
    user: AuthenticatedUser,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a cryptographically signed HMAC-SHA256 JWT access token."""
    now = int(time.time())
    if expires_delta:
        expire_seconds = int(expires_delta.total_seconds())
    else:
        expire_seconds = settings.auth_token_expire_minutes * 60

    exp = now + expire_seconds
    claims = {
        "sub": user.sub,
        "name": user.name,
        "role": user.role,
        "cases": user.cases,
        "iat": now,
        "exp": exp,
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
    }

    key = get_oct_key()
    token = jwt.encode({"alg": settings.auth_algorithm, "typ": "JWT"}, claims, key)
    return token


def decode_access_token(token: str) -> TokenPayload:
    """Decode and cryptographically verify a JWT access token with full claims and algorithm validation."""
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Authentication token is missing or empty.")

    key = get_oct_key()
    try:
        token_obj = jwt.decode(token, key, algorithms=[settings.auth_algorithm])
        claims = token_obj.claims
        header = token_obj.header
    except (BadSignatureError, DecodeError) as exc:
        raise InvalidTokenError(f"Invalid token signature or encoding: {exc}") from exc
    except Exception as exc:
        raise InvalidTokenError(f"Failed to decode token: {exc}") from exc

    # Enforce exact algorithm match
    alg = header.get("alg")
    if alg != settings.auth_algorithm:
        raise InvalidTokenError(f"Token signed with unexpected algorithm '{alg}'. Expected '{settings.auth_algorithm}'.")

    # Enforce issuer
    iss = claims.get("iss")
    if iss != settings.auth_issuer:
        raise InvalidTokenError(f"Token issuer mismatch: got '{iss}', expected '{settings.auth_issuer}'.")

    # Enforce audience
    aud = claims.get("aud")
    if aud != settings.auth_audience:
        raise InvalidTokenError(f"Token audience mismatch: got '{aud}', expected '{settings.auth_audience}'.")

    now = int(time.time())

    # Enforce expiration
    exp = claims.get("exp")
    if exp is None or int(exp) < now:
        raise TokenExpiredError("Authentication token has expired.")

    # Enforce issued-at (prevent tokens issued in the future)
    iat = claims.get("iat")
    if iat is None or int(iat) > now + 60:
        raise InvalidTokenError(f"Token issued in the future (iat={iat}, current={now}).")

    try:
        payload = TokenPayload.model_validate(claims)
        # Ensure role is a valid UserRole
        if payload.role not in (UserRole.CLINICIAN_REVIEWER, UserRole.ADMIN, UserRole.AUDITOR):
            raise InvalidTokenError(f"Invalid user role in token: '{payload.role}'.")
        return payload
    except Exception as exc:
        raise InvalidTokenError(f"Token claims schema mismatch: {exc}") from exc


def authenticate_synthetic_user(username: str, password: str) -> AuthenticatedUser | None:
    """Authenticate synthetic credentials using timing-attack resistant comparison."""
    account = _SYNTHETIC_USERS.get(username)
    if not account:
        return None

    expected_password = account["password"]
    if not secrets.compare_digest(password, expected_password):
        return None

    return account["user"]


def get_synthetic_user_by_username(username: str) -> AuthenticatedUser | None:
    """Lookup synthetic user by username."""
    account = _SYNTHETIC_USERS.get(username)
    if account:
        return account["user"]
    return None
