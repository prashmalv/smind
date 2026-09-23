"""Stores, catalogue, customers, and transactions — the substrate every module reads."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Store(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_store_tenant_code"),)

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    region: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    # mall | high-street | drive-thru | food-court | cloud-kitchen | standalone
    format: Mapped[str] = mapped_column(String(40), default="standalone", nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    floor_area_sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opened_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Product(IdMixin, TenantMixin, TimestampMixin, Base):
    """Menu item for QSR, SKU for retail. Same table, different label in the UI."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_product_tenant_sku"),)

    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="", index=True, nullable=False)
    subcategory: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    brand: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_combo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[str] = mapped_column(String(300), default="", nullable=False)

    @property
    def margin_pct(self) -> float:
        return 0.0 if self.price <= 0 else round((self.price - self.cost) / self.price * 100, 2)


class Customer(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_customer_tenant_external"),
        Index("ix_customer_tenant_lastorder", "tenant_id", "last_order_at"),
    )

    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    # Contact fields are optional and hashed at ingest when the tenant enables pseudonymisation.
    display_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    phone_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    age_band: Mapped[str] = mapped_column(String(16), default="", nullable=False)  # 18-24 …
    gender: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    home_store_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    signup_channel: Mapped[str] = mapped_column(String(40), default="", nullable=False)

    # Denormalised RFM facts, refreshed by the profiling module.
    first_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lifetime_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_basket_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class Order(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_order_tenant_external"),
        Index("ix_order_tenant_placed", "tenant_id", "placed_at"),
        Index("ix_order_tenant_store_placed", "tenant_id", "store_id", "placed_at"),
    )

    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    store_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # dine-in | takeaway | delivery | drive-thru | online | in-store
    channel: Mapped[str] = mapped_column(String(32), default="in-store", nullable=False)
    daypart: Mapped[str] = mapped_column(String(24), default="", index=True, nullable=False)

    gross_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    fulfilment_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)


class OrderItem(IdMixin, TenantMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (Index("ix_orderitem_tenant_product", "tenant_id", "product_id"),)

    order_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    line_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_addon: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
