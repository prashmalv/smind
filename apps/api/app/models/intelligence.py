"""Outputs of the reasoning layer: insights, segments, churn, offers, simulations, chat.

The concept doc's chain — Data → Insight → Reason → Action → Measurement — is literally
the shape of the `Insight` row: `headline` is the insight, `reasoning` is the why,
`actions` is what to do, and `outcome_*` closes the loop once the action was taken.
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


class Insight(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "insights"
    __table_args__ = (Index("ix_insight_tenant_detected", "tenant_id", "detected_at"),)

    module_key: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    # opportunity | risk | anomaly | trend | explanation
    kind: Mapped[str] = mapped_column(String(24), default="explanation", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    headline: Mapped[str] = mapped_column(String(300), nullable=False)      # 2. Insight
    reasoning: Mapped[str] = mapped_column(Text, default="", nullable=False)  # 3. Reason
    actions: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # 4. Action (JSON)
    evidence: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # JSON

    store_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_delta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_impact: Mapped[float | None] = mapped_column(Float, nullable=True)

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # new | acknowledged | actioned | dismissed | measured
    status: Mapped[str] = mapped_column(String(24), default="new", index=True, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 5. Measurement — filled after the action has had time to land.
    outcome_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    outcome_delta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SegmentAssignment(IdMixin, TenantMixin, TimestampMixin, Base):
    """Segments move with the customer — this table is rewritten on each profiling run."""

    __tablename__ = "segment_assignments"
    __table_args__ = (Index("ix_segassign_tenant_segment", "tenant_id", "segment_key"),)

    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    segment_key: Mapped[str] = mapped_column(String(48), nullable=False)
    previous_segment_key: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rationale: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    assigned_on: Mapped[date] = mapped_column(Date, nullable=False)


class ChurnScore(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "churn_scores"
    __table_args__ = (Index("ix_churn_tenant_risk", "tenant_id", "risk_band"),)

    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    probability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    risk_band: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    days_since_last_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expected_gap_days: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    top_driver: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    revenue_at_risk: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    scored_on: Mapped[date] = mapped_column(Date, nullable=False)


class NextBestOffer(IdMixin, TenantMixin, TimestampMixin, Base):
    """Customer → Context → Intent → Recommendation → Action, one row per customer."""

    __tablename__ = "next_best_offers"
    __table_args__ = (Index("ix_nbo_tenant_generated", "tenant_id", "generated_on"),)

    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    offer_type: Mapped[str] = mapped_column(String(40), default="cross_sell", nullable=False)
    offer_text: Mapped[str] = mapped_column(String(300), nullable=False)
    context: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    inferred_intent: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    propensity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expected_uplift: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="app", nullable=False)
    generated_on: Mapped[date] = mapped_column(Date, nullable=False)
    # pending | pushed | redeemed | ignored
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)


class SimulationRun(IdMixin, TenantMixin, TimestampMixin, Base):
    """A what-if evaluated before the decision is made."""

    __tablename__ = "simulation_runs"

    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scenario_type: Mapped[str] = mapped_column(String(48), nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    parameters: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # JSON
    results: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # JSON
    narrative: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    was_executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Conversation(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="New conversation", nullable=False)
    # text | voice
    modality: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Message(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_message_conv_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Which modules answered, and the numbers they returned — this is the audit trail.
    modules_used: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    was_voice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
