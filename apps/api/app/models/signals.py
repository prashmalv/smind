"""Unstructured and external signals: feedback, campaigns, competitors.

These are what let the platform answer *why* rather than only *what*.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Feedback(IdMixin, TenantMixin, TimestampMixin, Base):
    """One customer utterance from any listening channel, enriched at ingest."""

    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_tenant_captured", "tenant_id", "captured_at"),)

    # review | social | survey | complaint | call | chat | voice_kiosk
    source: Mapped[str] = mapped_column(String(32), default="review", index=True, nullable=False)
    channel_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    store_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("stores.id", ondelete="SET NULL"), index=True, nullable=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    body: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Enrichment written by the sentiment / VoC pipeline.
    sentiment: Mapped[str] = mapped_column(String(16), default="neutral", index=True, nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    themes: Mapped[str] = mapped_column(String(400), default="", nullable=False)  # csv
    is_actionable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Campaign(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    # discount | bundle | loyalty | winback | launch | awareness
    objective: Mapped[str] = mapped_column(String(40), default="discount", nullable=False)
    channel: Mapped[str] = mapped_column(String(40), default="app", nullable=False)
    offer_text: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_segment: Mapped[str] = mapped_column(String(60), default="all", nullable=False)

    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    reach: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    redemptions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attributed_revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="completed", nullable=False)

    @property
    def redemption_rate(self) -> float:
        return 0.0 if self.reach == 0 else round(self.redemptions / self.reach * 100, 2)

    @property
    def roi(self) -> float:
        return 0.0 if self.budget <= 0 else round(self.attributed_revenue / self.budget, 2)


class CompetitorSignal(IdMixin, TenantMixin, TimestampMixin, Base):
    """Public digital signal about a competitor: review, menu change, offer, price move."""

    __tablename__ = "competitor_signals"
    __table_args__ = (Index("ix_compsig_tenant_observed", "tenant_id", "observed_at"),)

    competitor_name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    # review | offer | price | menu | store_open | social
    signal_type: Mapped[str] = mapped_column(String(32), default="review", nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), default="neutral", nullable=False)
    price_point: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_url: Mapped[str] = mapped_column(String(400), default="", nullable=False)
