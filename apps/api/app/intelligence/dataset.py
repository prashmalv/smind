"""Loads a tenant's period data into pandas frames once, and hands the same frames to
every module in a run. Without this each of the thirteen modules would re-query Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import cached_property

import pandas as pd
from sqlalchemy import select

from app.intelligence.base import AnalysisContext
from app.models.commerce import Customer, Order, OrderItem, Product, Store
from app.models.signals import Campaign, CompetitorSignal, Feedback
from app.models.vision import Camera, CameraEvent


def _frame(rows: list, columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([dict(zip(columns, r, strict=True)) for r in rows])


@dataclass
class Dataset:
    """Period-scoped, tenant-scoped frames. Built once per analysis run."""

    ctx: AnalysisContext

    # ── orders in the current period ────────────────────────────────────────
    def _orders(self, start: datetime, end: datetime) -> pd.DataFrame:
        stmt = (
            select(
                Order.id, Order.store_id, Order.customer_id, Order.placed_at, Order.channel,
                Order.daypart, Order.gross_amount, Order.discount_amount, Order.net_amount,
                Order.item_count, Order.campaign_id, Order.fulfilment_minutes,
            )
            .where(Order.tenant_id == self.ctx.tenant_id)
            .where(Order.placed_at >= start, Order.placed_at < end)
        )
        if self.ctx.store_ids:
            stmt = stmt.where(Order.store_id.in_(self.ctx.store_ids))
        cols = [
            "order_id", "store_id", "customer_id", "placed_at", "channel", "daypart",
            "gross_amount", "discount_amount", "net_amount", "item_count", "campaign_id",
            "fulfilment_minutes",
        ]
        df = _frame(self.ctx.db.execute(stmt).all(), cols)
        if not df.empty:
            df["placed_at"] = pd.to_datetime(df["placed_at"], utc=True)
            df["date"] = df["placed_at"].dt.date
            df["hour"] = df["placed_at"].dt.hour
            df["dow"] = df["placed_at"].dt.day_name()
            # to_period drops the timezone and warns; truncate to the week's Monday instead.
            df["week"] = (
                df["placed_at"] - pd.to_timedelta(df["placed_at"].dt.dayofweek, unit="D")
            ).dt.strftime("%Y-%m-%d")
        return df

    @cached_property
    def orders(self) -> pd.DataFrame:
        return self._orders(self.ctx.period_start, self.ctx.period_end)

    @cached_property
    def prior_orders(self) -> pd.DataFrame:
        return self._orders(self.ctx.prior_start, self.ctx.prior_end)

    # ── line items joined to product attributes ─────────────────────────────
    def _items(self, orders: pd.DataFrame) -> pd.DataFrame:
        if orders.empty:
            return pd.DataFrame(
                columns=["order_id", "product_id", "quantity", "unit_price", "line_amount",
                         "is_addon", "name", "category", "price", "cost", "is_combo"]
            )
        order_ids = orders["order_id"].tolist()
        stmt = (
            select(
                OrderItem.order_id, OrderItem.product_id, OrderItem.quantity,
                OrderItem.unit_price, OrderItem.line_amount, OrderItem.is_addon,
            )
            .where(OrderItem.tenant_id == self.ctx.tenant_id)
            .where(OrderItem.order_id.in_(order_ids))
        )
        cols = ["order_id", "product_id", "quantity", "unit_price", "line_amount", "is_addon"]
        items = _frame(self.ctx.db.execute(stmt).all(), cols)
        if items.empty:
            return items
        return items.merge(self.products, on="product_id", how="left")

    @cached_property
    def items(self) -> pd.DataFrame:
        return self._items(self.orders)

    @cached_property
    def prior_items(self) -> pd.DataFrame:
        return self._items(self.prior_orders)

    # ── dimensions (not period-scoped) ──────────────────────────────────────
    @cached_property
    def products(self) -> pd.DataFrame:
        stmt = select(
            Product.id, Product.sku, Product.name, Product.category, Product.subcategory,
            Product.price, Product.cost, Product.is_combo, Product.is_active,
        ).where(Product.tenant_id == self.ctx.tenant_id)
        cols = ["product_id", "sku", "name", "category", "subcategory", "price", "cost",
                "is_combo", "is_active"]
        return _frame(self.ctx.db.execute(stmt).all(), cols)

    @cached_property
    def stores(self) -> pd.DataFrame:
        stmt = select(
            Store.id, Store.code, Store.name, Store.city, Store.region, Store.format,
            Store.is_active,
        ).where(Store.tenant_id == self.ctx.tenant_id)
        cols = ["store_id", "code", "store_name", "city", "region", "format", "is_active"]
        return _frame(self.ctx.db.execute(stmt).all(), cols)

    @cached_property
    def customers(self) -> pd.DataFrame:
        stmt = select(
            Customer.id, Customer.age_band, Customer.gender, Customer.city,
            Customer.home_store_id, Customer.first_order_at, Customer.last_order_at,
            Customer.order_count, Customer.lifetime_value, Customer.avg_basket_value,
            Customer.signup_channel,
        ).where(Customer.tenant_id == self.ctx.tenant_id)
        cols = ["customer_id", "age_band", "gender", "city", "home_store_id",
                "first_order_at", "last_order_at", "order_count", "lifetime_value",
                "avg_basket_value", "signup_channel"]
        df = _frame(self.ctx.db.execute(stmt).all(), cols)
        if not df.empty:
            for c in ("first_order_at", "last_order_at"):
                df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
        return df

    # ── signals ─────────────────────────────────────────────────────────────
    @cached_property
    def feedback(self) -> pd.DataFrame:
        stmt = (
            select(
                Feedback.id, Feedback.source, Feedback.store_id, Feedback.product_id,
                Feedback.captured_at, Feedback.body, Feedback.rating, Feedback.sentiment,
                Feedback.sentiment_score, Feedback.themes, Feedback.language,
            )
            .where(Feedback.tenant_id == self.ctx.tenant_id)
            .where(Feedback.captured_at >= self.ctx.period_start)
            .where(Feedback.captured_at < self.ctx.period_end)
        )
        cols = ["feedback_id", "source", "store_id", "product_id", "captured_at", "body",
                "rating", "sentiment", "sentiment_score", "themes", "language"]
        df = _frame(self.ctx.db.execute(stmt).all(), cols)
        if not df.empty:
            df["captured_at"] = pd.to_datetime(df["captured_at"], utc=True)
            df["date"] = df["captured_at"].dt.date
        return df

    @cached_property
    def prior_feedback(self) -> pd.DataFrame:
        stmt = (
            select(Feedback.sentiment, Feedback.themes, Feedback.sentiment_score, Feedback.body)
            .where(Feedback.tenant_id == self.ctx.tenant_id)
            .where(Feedback.captured_at >= self.ctx.prior_start)
            .where(Feedback.captured_at < self.ctx.prior_end)
        )
        return _frame(
            self.ctx.db.execute(stmt).all(),
            ["sentiment", "themes", "sentiment_score", "body"],
        )

    @cached_property
    def campaigns(self) -> pd.DataFrame:
        stmt = select(
            Campaign.id, Campaign.name, Campaign.objective, Campaign.channel,
            Campaign.discount_pct, Campaign.target_segment, Campaign.starts_on,
            Campaign.ends_on, Campaign.budget, Campaign.reach, Campaign.redemptions,
            Campaign.attributed_revenue, Campaign.status,
        ).where(Campaign.tenant_id == self.ctx.tenant_id)
        cols = ["campaign_id", "name", "objective", "channel", "discount_pct",
                "target_segment", "starts_on", "ends_on", "budget", "reach",
                "redemptions", "attributed_revenue", "status"]
        return _frame(self.ctx.db.execute(stmt).all(), cols)

    @cached_property
    def competitor_signals(self) -> pd.DataFrame:
        stmt = (
            select(
                CompetitorSignal.competitor_name, CompetitorSignal.signal_type,
                CompetitorSignal.city, CompetitorSignal.observed_at, CompetitorSignal.body,
                CompetitorSignal.sentiment, CompetitorSignal.price_point,
            )
            .where(CompetitorSignal.tenant_id == self.ctx.tenant_id)
            .where(CompetitorSignal.observed_at >= self.ctx.period_start)
        )
        cols = ["competitor_name", "signal_type", "city", "observed_at", "body",
                "sentiment", "price_point"]
        df = _frame(self.ctx.db.execute(stmt).all(), cols)
        if not df.empty:
            df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
        return df

    # ── camera ──────────────────────────────────────────────────────────────
    @cached_property
    def camera_events(self) -> pd.DataFrame:
        stmt = (
            select(
                CameraEvent.camera_id, CameraEvent.store_id, CameraEvent.zone_type,
                CameraEvent.window_start, CameraEvent.window_seconds, CameraEvent.footfall_in,
                CameraEvent.unique_visitors, CameraEvent.max_occupancy,
                CameraEvent.avg_queue_length, CameraEvent.max_queue_length,
                CameraEvent.avg_wait_seconds, CameraEvent.abandonment_count,
                CameraEvent.avg_dwell_seconds, CameraEvent.interaction_count,
                CameraEvent.demographics,
            )
            .where(CameraEvent.tenant_id == self.ctx.tenant_id)
            .where(CameraEvent.window_start >= self.ctx.period_start)
            .where(CameraEvent.window_start < self.ctx.period_end)
        )
        cols = ["camera_id", "store_id", "zone_type", "window_start", "window_seconds",
                "footfall_in", "unique_visitors", "max_occupancy", "avg_queue_length",
                "max_queue_length", "avg_wait_seconds", "abandonment_count",
                "avg_dwell_seconds", "interaction_count", "demographics"]
        df = _frame(self.ctx.db.execute(stmt).all(), cols)
        if not df.empty:
            df["window_start"] = pd.to_datetime(df["window_start"], utc=True)
            df["date"] = df["window_start"].dt.date
            df["hour"] = df["window_start"].dt.hour
        return df

    @cached_property
    def cameras(self) -> pd.DataFrame:
        stmt = select(
            Camera.id, Camera.code, Camera.name, Camera.store_id, Camera.zone_type,
            Camera.mode, Camera.is_active, Camera.last_seen_at,
        ).where(Camera.tenant_id == self.ctx.tenant_id)
        cols = ["camera_id", "code", "camera_name", "store_id", "zone_type", "mode",
                "is_active", "last_seen_at"]
        return _frame(self.ctx.db.execute(stmt).all(), cols)

    # ── convenience ─────────────────────────────────────────────────────────
    def store_name(self, store_id: str) -> str:
        if self.stores.empty:
            return store_id
        hit = self.stores[self.stores["store_id"] == store_id]
        return str(hit.iloc[0]["store_name"]) if not hit.empty else store_id

    def product_name(self, product_id: str) -> str:
        if self.products.empty:
            return product_id
        hit = self.products[self.products["product_id"] == product_id]
        return str(hit.iloc[0]["name"]) if not hit.empty else product_id

    @property
    def has_orders(self) -> bool:
        return not self.orders.empty

    # Every frame this class exposes. Kept explicit so warm() cannot silently miss one.
    FRAMES = (
        "orders", "prior_orders", "items", "prior_items", "products", "stores",
        "customers", "feedback", "prior_feedback", "campaigns", "competitor_signals",
        "camera_events", "cameras",
    )

    def warm(self) -> None:
        """Load every frame on the calling thread.

        The modules then run in parallel over pure pandas. A SQLAlchemy Session is not
        thread-safe, so every query has to happen before the fan-out — without this, a
        module that lazily touches a frame from a worker thread races the session and
        fails, which the registry then swallows into an empty result.
        """
        for name in self.FRAMES:
            getattr(self, name)
