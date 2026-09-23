"""Bringing a tenant's own data in.

ShopperMind does not replace the POS or the CRM — it sits above them. These endpoints are
the seam: push from a connector, or upload a CSV to get started before any integration
work happens.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, current_principal, load_tenant_or_404, require_manager
from app.models.commerce import Customer, Order, OrderItem, Product, Store
from app.models.signals import Campaign, CompetitorSignal, Feedback
from app.services.azure_language import enrich_sync

router = APIRouter(prefix="/ingest", tags=["ingest"])


class StoreIn(BaseModel):
    code: str
    name: str
    city: str = ""
    state: str = ""
    region: str = ""
    format: str = "standalone"
    latitude: float | None = None
    longitude: float | None = None


class ProductIn(BaseModel):
    sku: str
    name: str
    category: str = ""
    subcategory: str = ""
    price: float = 0.0
    cost: float = 0.0
    is_combo: bool = False


class OrderItemIn(BaseModel):
    sku: str
    quantity: int = 1
    unit_price: float = 0.0
    is_addon: bool = False


class OrderIn(BaseModel):
    external_id: str
    store_code: str
    customer_external_id: str | None = None
    placed_at: datetime
    channel: str = "in-store"
    gross_amount: float = 0.0
    discount_amount: float = 0.0
    items: list[OrderItemIn] = Field(default_factory=list)
    fulfilment_minutes: float | None = None


class FeedbackIn(BaseModel):
    source: str = "review"
    channel_name: str = ""
    store_code: str | None = None
    body: str
    rating: float | None = None
    captured_at: datetime | None = None
    language: str = "en"


def _daypart(dt: datetime) -> str:
    h = dt.hour
    if h < 11:
        return "breakfast"
    if h < 15:
        return "lunch"
    if h < 18:
        return "afternoon"
    if h < 22:
        return "dinner"
    return "late night"


@router.post("/stores", status_code=status.HTTP_201_CREATED)
def upsert_stores(
    stores: list[StoreIn],
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    existing = {
        s.code: s for s in db.scalars(select(Store).where(Store.tenant_id == tenant.id)).all()
    }
    limit = tenant.limits["stores"]
    created = updated = 0
    for s in stores:
        if s.code in existing:
            for field, value in s.model_dump().items():
                setattr(existing[s.code], field, value)
            updated += 1
        else:
            if len(existing) + created >= limit:
                raise HTTPException(
                    status_code=402,
                    detail=f"The {tenant.plan} plan includes {limit} stores.",
                )
            db.add(Store(tenant_id=tenant.id, **s.model_dump()))
            created += 1
    db.commit()
    return {"created": created, "updated": updated}


@router.post("/products", status_code=status.HTTP_201_CREATED)
def upsert_products(
    products: list[ProductIn],
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    existing = {
        p.sku: p for p in db.scalars(
            select(Product).where(Product.tenant_id == principal.tenant_id)).all()
    }
    created = updated = 0
    for p in products:
        if p.sku in existing:
            for field, value in p.model_dump().items():
                setattr(existing[p.sku], field, value)
            updated += 1
        else:
            db.add(Product(tenant_id=principal.tenant_id, **p.model_dump()))
            created += 1
    db.commit()
    return {"created": created, "updated": updated}


@router.post("/orders", status_code=status.HTTP_202_ACCEPTED)
def push_orders(
    orders: list[OrderIn],
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Push a batch of orders. Idempotent on external_id — a connector that retries a
    batch must not double-count revenue."""
    tid = principal.tenant_id
    stores = {
        s.code: s.id for s in db.scalars(select(Store).where(Store.tenant_id == tid)).all()
    }
    products = {
        p.sku: p for p in db.scalars(select(Product).where(Product.tenant_id == tid)).all()
    }
    customers = {
        c.external_id: c for c in db.scalars(
            select(Customer).where(Customer.tenant_id == tid)).all()
    }
    seen = set(db.scalars(
        select(Order.external_id).where(Order.tenant_id == tid)).all())

    created, skipped, errors = 0, 0, []
    for o in orders:
        if o.external_id in seen:
            skipped += 1
            continue
        store_id = stores.get(o.store_code)
        if store_id is None:
            errors.append(f"Unknown store '{o.store_code}' on order {o.external_id}")
            continue

        customer = None
        if o.customer_external_id:
            customer = customers.get(o.customer_external_id)
            if customer is None:
                customer = Customer(tenant_id=tid, external_id=o.customer_external_id,
                                    home_store_id=store_id)
                db.add(customer)
                db.flush()
                customers[o.customer_external_id] = customer

        placed = o.placed_at if o.placed_at.tzinfo else o.placed_at.replace(tzinfo=UTC)
        net = o.gross_amount - o.discount_amount
        order = Order(
            tenant_id=tid, external_id=o.external_id, store_id=store_id,
            customer_id=customer.id if customer else None, placed_at=placed,
            channel=o.channel, daypart=_daypart(placed), gross_amount=o.gross_amount,
            discount_amount=o.discount_amount, net_amount=net,
            item_count=sum(i.quantity for i in o.items),
            fulfilment_minutes=o.fulfilment_minutes,
        )
        db.add(order)
        db.flush()

        for item in o.items:
            product = products.get(item.sku)
            if product is None:
                errors.append(f"Unknown SKU '{item.sku}' on order {o.external_id}")
                continue
            price = item.unit_price or product.price
            db.add(OrderItem(
                tenant_id=tid, order_id=order.id, product_id=product.id,
                quantity=item.quantity, unit_price=price,
                line_amount=price * item.quantity, is_addon=item.is_addon,
            ))

        if customer:
            customer.order_count += 1
            customer.lifetime_value += net
            customer.last_order_at = placed
            if customer.first_order_at is None or placed < customer.first_order_at:
                customer.first_order_at = placed
            customer.avg_basket_value = round(
                customer.lifetime_value / max(customer.order_count, 1), 2)

        seen.add(o.external_id)
        created += 1

    db.commit()
    return {"created": created, "skipped_duplicates": skipped, "errors": errors[:20]}


@router.post("/feedback", status_code=status.HTTP_202_ACCEPTED)
def push_feedback(
    items: list[FeedbackIn],
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Ingest customer text from any listening channel.

    Enrichment — PII redaction, sentiment, themes — happens here, once, so every reading
    module works off the same interpretation of the same text.
    """
    tid = principal.tenant_id
    stores = {
        s.code: s.id for s in db.scalars(select(Store).where(Store.tenant_id == tid)).all()
    }
    created = 0
    for f in items:
        enriched = enrich_sync(f.body)
        captured = f.captured_at or datetime.now(UTC)
        db.add(Feedback(
            tenant_id=tid, source=f.source, channel_name=f.channel_name,
            store_id=stores.get(f.store_code or ""), captured_at=captured,
            body=enriched["body"], language=f.language, rating=f.rating,
            sentiment=enriched["sentiment"], sentiment_score=enriched["sentiment_score"],
            themes=enriched["themes"],
            is_actionable=enriched["sentiment"] == "negative" and bool(enriched["themes"]),
        ))
        created += 1
    db.commit()
    return {"created": created}


@router.post("/csv/{entity}", status_code=status.HTTP_202_ACCEPTED)
async def upload_csv(
    entity: str,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """CSV upload — the path a customer takes on day one, before any integration exists.

    Supported: stores, products, customers, feedback. Orders go through the JSON endpoint
    because they are nested.
    """
    if entity not in {"stores", "products", "customers", "feedback"}:
        raise HTTPException(
            status_code=400,
            detail="entity must be one of: stores, products, customers, feedback",
        )
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows:
        raise HTTPException(status_code=400, detail="The file has no data rows")

    tid = principal.tenant_id
    created, errors = 0, []

    if entity == "stores":
        for i, r in enumerate(rows, 2):
            try:
                db.add(Store(
                    tenant_id=tid, code=r.get("code") or f"S{i}", name=r.get("name", ""),
                    city=r.get("city", ""), state=r.get("state", ""),
                    region=r.get("region", ""), format=r.get("format", "standalone"),
                ))
                created += 1
            except Exception as exc:
                errors.append(f"Row {i}: {exc}")

    elif entity == "products":
        for i, r in enumerate(rows, 2):
            try:
                db.add(Product(
                    tenant_id=tid, sku=r.get("sku") or f"P{i}", name=r.get("name", ""),
                    category=r.get("category", ""), subcategory=r.get("subcategory", ""),
                    price=float(r.get("price") or 0), cost=float(r.get("cost") or 0),
                    is_combo=str(r.get("is_combo", "")).lower() in ("1", "true", "yes"),
                ))
                created += 1
            except Exception as exc:
                errors.append(f"Row {i}: {exc}")

    elif entity == "customers":
        for i, r in enumerate(rows, 2):
            try:
                db.add(Customer(
                    tenant_id=tid, external_id=r.get("external_id") or f"C{i}",
                    age_band=r.get("age_band", ""), gender=r.get("gender", ""),
                    city=r.get("city", ""), signup_channel=r.get("signup_channel", ""),
                ))
                created += 1
            except Exception as exc:
                errors.append(f"Row {i}: {exc}")

    else:  # feedback
        stores = {
            s.code: s.id for s in db.scalars(select(Store).where(Store.tenant_id == tid)).all()
        }
        for i, r in enumerate(rows, 2):
            body = r.get("body") or r.get("text") or r.get("review") or ""
            if not body.strip():
                continue
            enriched = enrich_sync(body)
            db.add(Feedback(
                tenant_id=tid, source=r.get("source", "review"),
                store_id=stores.get(r.get("store_code", "")),
                captured_at=datetime.now(UTC), body=enriched["body"],
                rating=float(r["rating"]) if r.get("rating") else None,
                sentiment=enriched["sentiment"], sentiment_score=enriched["sentiment_score"],
                themes=enriched["themes"],
            ))
            created += 1

    db.commit()
    return {"entity": entity, "rows_in_file": len(rows), "created": created,
            "errors": errors[:20]}


@router.get("/status")
def ingest_status(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    """What is connected, and what is not. The Data sources screen renders this."""
    tid = principal.tenant_id

    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.tenant_id == tid)) or 0

    def latest(model, column) -> str | None:
        value = db.scalar(select(func.max(column)).where(model.tenant_id == tid))
        return value.isoformat() if value else None

    from app.models.vision import CameraEvent

    sources = [
        {"key": "stores", "label": "Stores", "records": count(Store),
         "required": True, "how": "CSV upload or POST /ingest/stores"},
        {"key": "products", "label": "Catalogue", "records": count(Product),
         "required": True, "how": "CSV upload or POST /ingest/products"},
        {"key": "orders", "label": "Transactions (POS)", "records": count(Order),
         "required": True, "how": "POST /ingest/orders from your POS connector",
         "last_seen": latest(Order, Order.placed_at)},
        {"key": "customers", "label": "Customers (CRM)", "records": count(Customer),
         "required": False, "how": "CSV upload or created automatically from orders"},
        {"key": "feedback", "label": "Feedback and reviews", "records": count(Feedback),
         "required": False, "how": "POST /ingest/feedback from your review sources",
         "last_seen": latest(Feedback, Feedback.captured_at)},
        {"key": "campaigns", "label": "Campaigns", "records": count(Campaign),
         "required": False, "how": "POST /ingest/campaigns from your CRM"},
        {"key": "competitor_signals", "label": "Competitor signals",
         "records": count(CompetitorSignal), "required": False,
         "how": "Listening connector or manual upload"},
        {"key": "cameras", "label": "In-store cameras", "records": count(CameraEvent),
         "required": False, "how": "Edge agent posting to /cameras/events",
         "last_seen": latest(CameraEvent, CameraEvent.window_start)},
    ]
    for s in sources:
        s["connected"] = s["records"] > 0

    missing_required = [s["label"] for s in sources if s["required"] and not s["connected"]]
    return {
        "sources": sources,
        "ready": not missing_required,
        "missing_required": missing_required,
        "modules_blocked": _blocked_modules(sources),
    }


def _blocked_modules(sources: list[dict]) -> list[dict]:
    """Say plainly which modules cannot run yet and what would unblock them."""
    connected = {s["key"]: s["connected"] for s in sources}
    needs = {
        "sentiment_intelligence": ["feedback"],
        "voice_of_customer": ["feedback"],
        "competitor_intelligence": ["competitor_signals"],
        "campaign_intelligence": ["campaigns"],
        "store_vision": ["cameras"],
        "basket_analysis": ["orders", "products"],
        "menu_intelligence": ["orders", "products"],
        "price_sensitivity": ["orders", "products"],
        "churn_intelligence": ["orders", "customers"],
        "next_best_offer": ["orders", "products", "customers"],
    }
    blocked = []
    for module, required in needs.items():
        missing = [r for r in required if not connected.get(r)]
        if missing:
            blocked.append({"module_key": module, "missing": missing})
    return blocked
