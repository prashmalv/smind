from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.tenant import VERTICALS


class RegisterRequest(BaseModel):
    """Self-service signup. Creates the tenant and its owner in one step."""

    company_name: str = Field(min_length=2, max_length=160)
    vertical: str = Field(default="qsr")
    country: str = Field(default="IN", min_length=2, max_length=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Kolkata")

    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    job_title: str = Field(default="", max_length=120)

    seed_demo_data: bool = Field(
        default=True,
        description="Populate the workspace with a realistic demo estate so the platform is "
                    "explorable before the POS is connected.",
    )

    @field_validator("vertical")
    @classmethod
    def known_vertical(cls, v: str) -> str:
        if v not in VERTICALS:
            raise ValueError(f"vertical must be one of {', '.join(VERTICALS)}")
        return v

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if v.isalpha() or v.isdigit():
            raise ValueError("Password must mix letters with numbers or symbols")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str | None = Field(
        default=None,
        description="Required only when the same email exists in more than one workspace.",
    )


class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: str = "viewer"
    job_title: str = ""
    password: str = Field(min_length=10)


class TenantOut(BaseModel):
    id: str
    name: str
    slug: str
    vertical: str
    currency: str
    country: str
    timezone: str
    plan: str
    camera_enabled: bool
    voice_enabled: bool


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    job_title: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserOut
    tenant: TenantOut
