"""In-store camera intelligence.

Design rule: raw frames never leave the store unless the tenant explicitly opts in. The
edge agent runs detection locally (or calls Azure AI Vision), then posts *anonymous
aggregate events* — counts, dwell seconds, zone transitions. No face templates, no
identity, no biometric join to the customer table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin

# Zones are how a camera's field of view is carved up for analysis.
ZONE_TYPES = ("entrance", "queue", "counter", "aisle", "display", "seating", "exit", "drive-thru")


class Camera(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "cameras"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_camera_tenant_code"),)

    code: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    store_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_type: Mapped[str] = mapped_column(String(32), default="entrance", nullable=False)
    # Connection string is stored for the edge agent only; never surfaced to the browser.
    stream_url: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    # live | simulated | offline
    mode: Mapped[str] = mapped_column(String(16), default="simulated", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Privacy posture, per camera.
    blur_faces: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retain_frames: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retention_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @property
    def is_healthy(self) -> bool:
        """Reported within the last fifteen minutes.

        `last_seen_at` comes back naive from backends that do not store an offset
        (SQLite, and Postgres columns written before a migration), so it is coerced to
        UTC rather than assumed — subtracting a naive from an aware datetime raises.
        """
        if not self.is_active or self.last_seen_at is None:
            return False
        from datetime import UTC

        from app.models.base import utcnow

        last = self.last_seen_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (utcnow() - last).total_seconds() < 900


class CameraEvent(IdMixin, TenantMixin, Base):
    """One aggregated observation window from one camera. Anonymous by construction."""

    __tablename__ = "camera_events"
    __table_args__ = (
        Index("ix_camevent_tenant_window", "tenant_id", "window_start"),
        Index("ix_camevent_tenant_camera", "tenant_id", "camera_id", "window_start"),
    )

    camera_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("cameras.id", ondelete="CASCADE"), index=True, nullable=False
    )
    store_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_type: Mapped[str] = mapped_column(String(32), default="entrance", nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)

    # Core counts
    footfall_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    footfall_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_visitors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_occupancy: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Queue and service
    avg_queue_length: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_queue_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_wait_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    abandonment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Engagement
    avg_dwell_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    interaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Anonymous demographic distribution (bands only; no identity, no stored template)
    demographics: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # JSON
    detector: Mapped[str] = mapped_column(String(48), default="local", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class CameraAlert(IdMixin, TenantMixin, TimestampMixin, Base):
    """A camera-derived condition worth someone's attention right now."""

    __tablename__ = "camera_alerts"
    __table_args__ = (Index("ix_camalert_tenant_raised", "tenant_id", "raised_at"),)

    camera_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    store_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # queue_breach | occupancy_breach | camera_offline | conversion_drop | dwell_anomaly
    alert_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    message: Mapped[str] = mapped_column(String(400), nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
