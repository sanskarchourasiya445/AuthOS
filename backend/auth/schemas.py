"""Authentication and authorization schemas."""
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class UserRole(str, Enum):
    """Supported actor roles for authorization."""
    CLINICIAN_REVIEWER = "clinician_reviewer"
    ADMIN = "admin"
    AUDITOR = "auditor"


class AuthenticatedUser(BaseModel):
    """Domain model of an authenticated actor."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sub: str = Field(description="Unique actor identifier (e.g. REV-001)")
    name: str = Field(description="Full display name (e.g. Dr. Sarah Chen, MD)")
    role: str = Field(description="Assigned role: clinician_reviewer, admin, or auditor")
    cases: list[str] = Field(
        default_factory=list,
        description="Explicit list of authorized case IDs, or ['*'] for unrestricted access",
    )


class TokenPayload(BaseModel):
    """Cryptographic JWT token claims."""
    model_config = ConfigDict(extra="ignore")

    sub: str
    name: str
    role: UserRole
    cases: list[str] = Field(default_factory=list)
    exp: int
    iat: int
    iss: str = "authos"
    aud: str = "authos-api"


class TokenRequest(BaseModel):
    """Synthetic credentials request for local dev / testing."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str
    password: str


class TokenResponse(BaseModel):
    """Bearer token response payload."""
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthenticatedUser
