"""Module runs, the pulse, and the insight loop."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, current_principal, load_tenant_or_404
from app.intelligence.base import AnalysisContext
from app.intelligence.registry import BY_KEY, catalogue, persist_findings, run_all, run_module, shopper_pulse
from app.intelligence.segments import SEGMENTS
from app.models.intelligence import Insight

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def build_ctx(
    principal: Principal, db: Session, period_days: int = 30,
    store_ids: list[str] | None = None,
) -> AnalysisContext:
    tenant = load_tenant_or_404(db, principal.tenant_id)
    return AnalysisContext(
        db=db, tenant_id=tenant.id, period_days=period_days,
        period_end=datetime.now(UTC), store_ids=store_ids,
        currency=tenant.currency, vertical=tenant.vertical,
    )


@router.get("/modules")
def list_modules(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    """The module directory, grouped by the five questions from the concept doc."""
    tenant = load_tenant_or_404(db, principal.tenant_id)
    mods = catalogue()
    grouped: dict[str, list] = {}
    for m in mods:
        grouped.setdefault(m["question"], []).append(m)
    return {
        "vertical": tenant.vertical,
        "modules": mods,
        "by_question": grouped,
        "segments": [
            {"key": s.key, "label": s.label, "who": s.who, "respond_with": s.respond_with}
            for s in SEGMENTS
        ],
        "stack": [
            {"step": 1, "name": "Listen", "detail": "Customer reviews, voice, social, feedback"},
            {"step": 2, "name": "Understand", "detail": "Segments, sentiment, intent, preferences"},
            {"step": 3, "name": "Predict", "detail": "Demand, churn, next purchase, trends"},
            {"step": 4, "name": "Recommend", "detail": "Offers, combos, menu, pricing"},
            {"step": 5, "name": "Act", "detail": "Campaigns, CRM, personalisation, store actions"},
            {"step": 6, "name": "Learn", "detail": "Measure response and feed the results back"},
        ],
    }


@router.get("/pulse")
def pulse(
    period_days: int = Query(30, ge=1, le=365),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """The command center home screen."""
    return shopper_pulse(build_ctx(principal, db, period_days))


@router.get("/modules/{module_key}")
def run_one(
    module_key: str,
    period_days: int = Query(30, ge=1, le=365),
    store_ids: list[str] | None = Query(None),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    if module_key not in BY_KEY:
        raise HTTPException(status_code=404, detail=f"No module '{module_key}'")
    ctx = build_ctx(principal, db, period_days, store_ids)
    return run_module(module_key, ctx).to_dict()


@router.post("/run")
def run_many(
    module_keys: list[str] = Body(..., embed=True),
    period_days: int = Body(30, embed=True),
    persist: bool = Body(False, embed=True),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    unknown = [k for k in module_keys if k not in BY_KEY]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown modules: {', '.join(unknown)}")
    ctx = build_ctx(principal, db, period_days)
    results = run_all(ctx, module_keys)
    written = persist_findings(ctx, results) if persist else 0
    return {
        "period": ctx.label(),
        "results": {k: v.to_dict() for k, v in results.items()},
        "insights_written": written,
    }


@router.post("/refresh")
def refresh_all(
    period_days: int = Body(30, embed=True),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Run every module and persist the findings. This is what the nightly job calls."""
    principal.require("analyst")
    ctx = build_ctx(principal, db, period_days)
    results = run_all(ctx)
    written = persist_findings(ctx, results)
    _persist_derived(ctx, results)
    return {
        "period": ctx.label(),
        "modules_run": len(results),
        "insights_written": written,
        "summary": {k: v.headline_metrics for k, v in results.items()},
    }


def _persist_derived(ctx: AnalysisContext, results: dict) -> None:
    """Write the per-customer outputs — segments, churn scores, offers — so the rest of the
    product (and any downstream CRM push) can read them without re-running the modules."""
    from datetime import date

    from sqlalchemy import delete

    from app.models.intelligence import ChurnScore, NextBestOffer, SegmentAssignment

    today = date.today()

    profiling = results.get("customer_profiling")
    if profiling and profiling.tables.get("_assignments"):
        previous = {
            row.customer_id: row.segment_key
            for row in ctx.db.scalars(
                select(SegmentAssignment).where(SegmentAssignment.tenant_id == ctx.tenant_id)
            ).all()
        }
        ctx.db.execute(
            delete(SegmentAssignment).where(SegmentAssignment.tenant_id == ctx.tenant_id))
        for row in profiling.tables["_assignments"]:
            ctx.db.add(SegmentAssignment(
                tenant_id=ctx.tenant_id, customer_id=row["customer_id"],
                segment_key=row["segment_key"],
                previous_segment_key=previous.get(row["customer_id"], ""),
                score=float(row.get("monetary") or 0), rationale=row.get("rationale", "")[:400],
                assigned_on=today,
            ))

    churn = results.get("churn_intelligence")
    if churn and churn.tables.get("_scores"):
        ctx.db.execute(delete(ChurnScore).where(ChurnScore.tenant_id == ctx.tenant_id))
        for row in churn.tables["_scores"]:
            ctx.db.add(ChurnScore(
                tenant_id=ctx.tenant_id, customer_id=row["customer_id"],
                probability=float(row["probability"]), risk_band=str(row["risk_band"]),
                days_since_last_order=int(row["days_since"]),
                expected_gap_days=float(row["expected_gap"]),
                top_driver=str(row["top_driver"])[:200],
                revenue_at_risk=float(row["revenue_at_risk"]), scored_on=today,
            ))

    nbo = results.get("next_best_offer")
    if nbo and nbo.tables.get("_offers"):
        ctx.db.execute(delete(NextBestOffer).where(NextBestOffer.tenant_id == ctx.tenant_id))
        for row in nbo.tables["_offers"]:
            ctx.db.add(NextBestOffer(
                tenant_id=ctx.tenant_id, customer_id=row["customer_id"],
                product_id=row.get("product_id"), offer_type=row["offer_type"],
                offer_text=row["offer_text"][:300], context=row["context"][:300],
                inferred_intent=row["inferred_intent"][:200],
                propensity=float(row["propensity"]),
                expected_uplift=float(row["expected_uplift"]),
                channel=row["channel"], generated_on=today,
            ))
    ctx.db.commit()


# ── the insight loop: measurement closes it ─────────────────────────────────
@router.get("/insights")
def list_insights(
    status_filter: str | None = Query(None, alias="status"),
    module_key: str | None = None,
    severity: str | None = None,
    limit: int = Query(50, le=200),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    stmt = select(Insight).where(Insight.tenant_id == principal.tenant_id)
    if status_filter:
        stmt = stmt.where(Insight.status == status_filter)
    if module_key:
        stmt = stmt.where(Insight.module_key == module_key)
    if severity:
        stmt = stmt.where(Insight.severity == severity)
    rows = db.scalars(stmt.order_by(Insight.detected_at.desc()).limit(limit)).all()
    return [_insight_out(i) for i in rows]


@router.patch("/insights/{insight_id}")
def update_insight(
    insight_id: str,
    status_value: str | None = Body(None, embed=True, alias="status"),
    assigned_to: str | None = Body(None, embed=True),
    outcome_note: str | None = Body(None, embed=True),
    outcome_delta_pct: float | None = Body(None, embed=True),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Move an insight along the loop, and record what actually happened.

    Setting an outcome is step five of the doc's chain — the part that makes the next run
    of this module better, and the part most analytics products never build.
    """
    insight = db.get(Insight, insight_id)
    if insight is None or insight.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Insight not found")

    allowed = {"new", "acknowledged", "actioned", "dismissed", "measured"}
    if status_value:
        if status_value not in allowed:
            raise HTTPException(status_code=400, detail=f"status must be one of {allowed}")
        insight.status = status_value
    if assigned_to is not None:
        insight.assigned_to = assigned_to
    if outcome_note is not None:
        insight.outcome_note = outcome_note
    if outcome_delta_pct is not None:
        insight.outcome_delta_pct = outcome_delta_pct
    if outcome_note or outcome_delta_pct is not None:
        insight.measured_at = datetime.now(UTC)
        insight.status = "measured"

    db.commit()
    db.refresh(insight)
    return _insight_out(insight)


@router.get("/insights/measurement")
def measurement_summary(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    """How the platform is doing at its own job — the Learn step, made visible."""
    rows = db.scalars(
        select(Insight).where(Insight.tenant_id == principal.tenant_id)
    ).all()
    measured = [i for i in rows if i.outcome_delta_pct is not None]
    actioned = [i for i in rows if i.status in ("actioned", "measured")]
    positive = [i for i in measured if (i.outcome_delta_pct or 0) > 0]
    return {
        "total_insights": len(rows),
        "actioned": len(actioned),
        "measured": len(measured),
        "action_rate_pct": round(len(actioned) / max(len(rows), 1) * 100, 1),
        "hit_rate_pct": round(len(positive) / max(len(measured), 1) * 100, 1),
        "avg_outcome_delta_pct": round(
            sum(i.outcome_delta_pct or 0 for i in measured) / max(len(measured), 1), 2),
        "by_module": [
            {
                "module_key": key,
                "insights": len([i for i in rows if i.module_key == key]),
                "measured": len([i for i in measured if i.module_key == key]),
                "avg_delta_pct": round(
                    sum(i.outcome_delta_pct or 0 for i in measured if i.module_key == key)
                    / max(len([i for i in measured if i.module_key == key]), 1), 2),
            }
            for key in sorted({i.module_key for i in rows})
        ],
    }


def _insight_out(i: Insight) -> dict:
    module = BY_KEY.get(i.module_key)
    return {
        "id": i.id,
        "module_key": i.module_key,
        "module_title": module.title if module else i.module_key,
        "kind": i.kind,
        "severity": i.severity,
        "confidence": i.confidence,
        "headline": i.headline,
        "reasoning": i.reasoning,
        "actions": json.loads(i.actions or "[]"),
        "evidence": json.loads(i.evidence or "{}"),
        "metric_value": i.metric_value,
        "metric_delta_pct": i.metric_delta_pct,
        "estimated_impact": i.estimated_impact,
        "store_id": i.store_id,
        "product_id": i.product_id,
        "detected_at": i.detected_at.isoformat() if i.detected_at else None,
        "status": i.status,
        "assigned_to": i.assigned_to,
        "outcome_note": i.outcome_note,
        "outcome_delta_pct": i.outcome_delta_pct,
        "measured_at": i.measured_at.isoformat() if i.measured_at else None,
    }
