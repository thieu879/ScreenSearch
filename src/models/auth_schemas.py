"""Request and response schemas for the authentication and user-management API.

Separated from ``src/models/schemas.py`` so the search contract (frozen) and the auth
contract (new) can evolve independently.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---------------------------------------------------------------------------
# Auth — request bodies
# ---------------------------------------------------------------------------


class SendOtpRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(..., pattern=r"^(register|forgot_password)$", description="OTP purpose")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit OTP code sent to email")
    full_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, min_length=3, max_length=50)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit OTP code")
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class GoogleLoginRequest(BaseModel):
    code: str | None = Field(default=None, description="Google OAuth authorization code")
    credential: str | None = Field(default=None, description="Google ID Token")
    redirect_uri: str | None = Field(default=None, description="OAuth redirect URI used by client")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, min_length=3, max_length=50)
    avatar: str | None = Field(default=None, max_length=2048)


class AdminUpdateUserRequest(BaseModel):
    full_name: str | None = None
    username: str | None = None
    role: str | None = Field(default=None, pattern=r"^(Admin|User)$")
    status: str | None = Field(default=None, pattern=r"^(active|disabled|banned)$")


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, min_length=2, max_length=50)
    role: str = Field(default="User", pattern=r"^(Admin|User)$")
    status: str = Field(default="active", pattern=r"^(active|disabled|banned)$")


class ServiceStatusItem(BaseModel):
    id: str
    name: str
    subTitle: str  # noqa: N815
    icon: str
    status: str
    uptime: str
    responseTime: int  # noqa: N815
    throughput: str
    host: str
    port: int
    maxConnections: int  # noqa: N815
    description: str


class SystemStatsResponse(BaseModel):
    total_users: int
    active_users: int
    disabled_users: int
    admin_users: int
    total_frames: int
    total_reviews: int
    total_embeddings: int
    cpu_usage: float
    ram_usage: float
    storage_usage: float
    storage_total_gb: float
    storage_free_gb: float
    services: list[ServiceStatusItem]


# ---------------------------------------------------------------------------
# Auth — response bodies
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """Public user profile — never includes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    username: str | None = None
    full_name: str | None = None
    avatar: str | None = None
    role: str
    status: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    message: str


class AuthResponse(BaseModel):
    """Returned on login / refresh — the tokens themselves travel in cookies, not here."""

    message: str
    user: UserResponse
