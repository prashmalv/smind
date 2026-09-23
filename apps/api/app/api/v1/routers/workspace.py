"""Workspace settings, stores, catalogue, customers, offers — the admin surface."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import Principal, current_principal, load_tenant_or_404, require_admin
from app.intelligence.segments import label as segment_label
from app.models.commerce import Customer, Order, Product, Store
from app.models.intelligence import ChurnScore, NextBestOffer, SegmentAssignment

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/settings")
def get_settings_(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    return {
        "tenant": {
            "id": tenant.id, "name": tenant.name, "slug": tenant.slug,
            "vertical": tenant.vertical, "country": tenant.country,
            "currency": tenant.currency, "timezone": tenant.timezone,
            "plan": tenant.plan, "limits": tenant.limits,
            "camera_enabled": tenant.camera_enabled, "voice_enabled": tenant.voice_enabled,
            "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None,
        },
        "usage": {
            "stores": db.scalar(select(func.count()).select_from(Store)
                                .where(Store.tenant_id == tenant.id)) or 0,
            "products": db.scalar(select(func.count()).select_from(Product)
                                  .where(Product.tenant_id == tenant.id)) or 0,
            "customers": db.scalar(select(func.count()).select_from(Customer)
                                   .where(Customer.tenant_id == tenant.id)) or 0,
            "orders": db.scalar(select(func.count()).select_from(Order)
                                .where(Order.tenant_id == tenant.id)) or 0,
        },
        "platform": {
            # What is actually wired up in this deployment. The UI uses this to explain
            # itself honestly rather than showing a feature that will not work.
            "azure_openai": settings.openai_enabled,
            "azure_speech": settings.speech_enabled,
            "azure_vision": settings.vision_enabled,
            "azure_language": settings.language_enabled,
            "environment": settings.shoppermind_env,
        },
    }


@router.patch("/settings")
def update_settings(
    camera_enabled: bool | None = Body(None, embed=True),
    voice_enabled: bool | None = Body(None, embed=True),
    timezone: str | None = Body(None, embed=True),
    currency: str | None = Body(None, embed=True),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    if camera_enabled is not None:
        tenant.camera_enabled = camera_enabled
    if voice_enabled is not None:
        tenant.voice_enabled = voice_enabled
    if timezone:
        tenant.timezone = timezone
    if currency:
        tenant.currency = currency.upper()[:3]
    db.commit()
    return {"updated": True}


@router.get("/stores")
def list_stores(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    rows = db.scalars(
        select(Store).where(Store.tenant_id == principal.tenant_id).order_by(Store.name)).all()
    return [
        {"id": s.id, "code": s.code, "name": s.name, "city": s.city, "region": s.region,
         "format": s.format, "is_active": s.is_active}
        for s in rows
    ]


@router.get("/products")
def list_products(
    category: str | None = None,
    limit: int = Query(200, le=1000),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    stmt = select(Product).where(Product.tenant_id == principal.tenant_id)
    if category:
        stmt = stmt.where(Product.category == category)
    rows = db.scalars(stmt.order_by(Product.category, Product.name).limit(limit)).all()
    return [
        {"id": p.id, "sku": p.sku, "name": p.name, "category": p.category,
         "price": p.price, "cost": p.cost, "margin_pct": p.margin_pct,
         "is_combo": p.is_combo, "is_active": p.is_active}
        for p in rows
    ]


@router.get("/customers")
def list_customers(
    segment: str | None = None,
    risk_band: str | None = None,
    limit: int = Query(100, le=500),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Customers with their current segment, churn score, and pending offer.

    This is the screen a marketing head actually exports — so it joins the three derived
    tables rather than making them click through three pages.
    """
    tid = principal.tenant_id
    segments = {
        s.customer_id: s for s in db.scalars(
            select(SegmentAssignment).where(SegmentAssignment.tenant_id == tid)).all()
    }
    churn = {
        c.customer_id: c for c in db.scalars(
            select(ChurnScore).where(ChurnScore.tenant_id == tid)).all()
    }
    offers = {
        o.customer_id: o for o in db.scalars(
            select(NextBestOffer).where(NextBestOffer.tenant_id == tid)).all()
    }

    stmt = select(Customer).where(Customer.tenant_id == tid)
    rows = db.scalars(stmt.order_by(Customer.lifetime_value.desc()).limit(limit * 3)).all()

    out = []
    for c in rows:
        seg = segments.get(c.id)
        risk = churn.get(c.id)
        offer = offers.get(c.id)
        if segment and (not seg or seg.segment_key != segment):
            continue
        if risk_band and (not risk or risk.risk_band != risk_band):
            continue
        out.append({
            "id": c.id, "external_id": c.external_id, "display_name": c.display_name,
            "age_band": c.age_band, "city": c.city, "order_count": c.order_count,
            "lifetime_value": round(c.lifetime_value, 0),
            "avg_basket_value": round(c.avg_basket_value, 0),
            "last_order_at": c.last_order_at.isoformat() if c.last_order_at else None,
            "segment": segment_label(seg.segment_key) if seg else None,
            "segment_key": seg.segment_key if seg else None,
            "segment_moved_from": (
                segment_label(seg.previous_segment_key)
                if seg and seg.previous_segment_key and seg.previous_segment_key != seg.segment_key
                else None
            ),
            "segment_rationale": seg.rationale if seg else None,
            "churn_probability": round(risk.probability, 3) if risk else None,
            "risk_band": risk.risk_band if risk else None,
            "churn_driver": risk.top_driver if risk else None,
            "revenue_at_risk": round(risk.revenue_at_risk, 0) if risk else None,
            "next_best_offer": offer.offer_text if offer else None,
            "offer_type": offer.offer_type if offer else None,
            "offer_propensity": round(offer.propensity, 3) if offer else None,
            "offer_context": offer.context if offer else None,
            "inferred_intent": offer.inferred_intent if offer else None,
        })
        if len(out) >= limit:
            break
    return out


@router.get("/offers")
def list_offers(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, le=500),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    stmt = select(NextBestOffer).where(NextBestOffer.tenant_id == principal.tenant_id)
    if status_filter:
        stmt = stmt.where(NextBestOffer.status == status_filter)
    rows = db.scalars(stmt.order_by(NextBestOffer.propensity.desc()).limit(limit)).all()
    products = {
        p.id: p.name for p in db.scalars(
            select(Product).where(Product.tenant_id == principal.tenant_id)).all()
    }
    return [
        {
            "id": o.id, "customer_id": o.customer_id, "offer_type": o.offer_type,
            "offer_text": o.offer_text, "product": products.get(o.product_id or "", ""),
            "context": o.context, "inferred_intent": o.inferred_intent,
            "propensity": round(o.propensity, 3),
            "expected_uplift": round(o.expected_uplift, 0),
            "channel": o.channel, "status": o.status,
            "generated_on": o.generated_on.isoformat() if o.generated_on else None,
        }
        for o in rows
    ]


@router.post("/offers/push")
def push_offers(
    offer_ids: list[str] = Body(..., embed=True),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Mark offers as pushed to the CRM.

    ShopperMind decides *what* to offer; the CRM delivers it. This endpoint is the handoff
    point, and it records the handoff so the response can be measured against it later.
    """
    principal.require("manager")
    rows = db.scalars(
        select(NextBestOffer).where(
            NextBestOffer.tenant_id == principal.tenant_id,
            NextBestOffer.id.in_(offer_ids),
        )
    ).all()
    for o in rows:
        o.status = "pushed"
    db.commit()
    return {
        "pushed": len(rows),
        "generated_on": date.today().isoformat(),
        "note": "Deliver these through your CRM or app. Report redemptions back via "
                "/ingest/orders with the campaign_id set, so the loop closes.",
    }


@router.get("/segments")
def segment_breakdown(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    """Segment counts plus movement — who arrived in each segment since the last run."""
    rows = db.scalars(
        select(SegmentAssignment).where(SegmentAssignment.tenant_id == principal.tenant_id)
    ).all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No segments assigned yet. Run POST /intelligence/refresh first.",
        )

    counts: dict[str, int] = {}
    movement: dict[str, dict[str, int]] = {}
    for r in rows:
        counts[r.segment_key] = counts.get(r.segment_key, 0) + 1
        if r.previous_segment_key and r.previous_segment_key != r.segment_key:
            movement.setdefault(r.segment_key, {})
            movement[r.segment_key][r.previous_segment_key] = (
                movement[r.segment_key].get(r.previous_segment_key, 0) + 1
            )

    return {
        "total_customers": len(rows),
        "segments": [
            {
                "key": key, "label": segment_label(key), "customers": n,
                "share_pct": round(n / len(rows) * 100, 1),
                "arrived_from": [
                    {"segment": segment_label(k), "customers": v}
                    for k, v in sorted(movement.get(key, {}).items(), key=lambda x: -x[1])
                ],
            }
            for key, n in sorted(counts.items(), key=lambda x: -x[1])
        ],
        "movement_note": "A customer is never permanently assigned. These counts are from the "
                         "most recent profiling run; 'arrived from' shows who moved since the "
                         "run before it.",
    }
