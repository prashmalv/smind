"""Tenant, user, and subscription — the SaaS control plane."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin

# Verticals the platform ships with. The intelligence modules are vertical-neutral;
# only labels and a handful of module defaults change per vertical.
VERTICALS = ("qsr", "retail", "grocery", "pharmacy", "cafe", "fashion")

# Trial limits are set to fit the seeded demo estate with room to add to it. A trial
# that ships ten demo stores and then refuses the eleventh camera reads as a bug, not
# as a limit, so the ceiling sits above what signup creates.
PLANS = {
    "trial": {"stores": 12, "cameras": 24, "seats": 5, "modules": "all"},
    "growth": {"stores": 60, "cameras": 180, "seats": 25, "modules": "all"},
    "enterprise": {"stores": 2000, "cameras": 6000, "seats": 500, "modules": "all"},
}


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    vertical: Mapped[str] = mapped_column(String(32), default="qsr", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="IN", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)

    plan: Mapped[str] = mapped_column(String(32), default="trial", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Feature switches a tenant admin controls from Settings.
    camera_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def limits(self) -> dict:
        return PLANS.get(self.plan, PLANS["trial"])


class User(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

    email: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # owner | admin | manager | analyst | viewer
    role: Mapped[str] = mapped_column(String(24), default="viewer", nullable=False)
    job_title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(IdMixin, TenantMixin, TimestampMixin, Base):
    """Used by edge camera agents and POS connectors — machine callers, not humans."""

    __tablename__ = "api_keys"

    label: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(64), default="ingest", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
