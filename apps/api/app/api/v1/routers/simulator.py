"""Shopper Simulator — test the decision before you make it."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, current_principal, load_tenant_or_404
from app.intelligence.base import AnalysisContext
from app.models.intelligence import SimulationRun
from app.simulator.engine import parse_question, run_scenario

router = APIRouter(prefix="/simulator", tags=["simulator"])

SCENARIOS = [
    {"key": "price_change", "label": "Change a price",
     "example": "What happens if we increase the combo price by ₹20?",
     "evaluates": ["Expected demand impact", "Average order value impact", "Margin impact",
                   "Customer segment impact", "Store-level differences"]},
    {"key": "new_item", "label": "Launch a new item",
     "example": "What if we launch a ₹149 value meal?",
     "evaluates": ["Likely customer segments", "Cannibalisation", "Expected basket impact",
                   "Potential volume impact", "Stores where it could work",
                   "Products likely to be displaced"]},
    {"key": "bundle", "label": "Test a bundle",
     "example": "What if we bundle fries with every burger at 15% off?",
     "evaluates": ["Attachment uplift", "Margin given away", "Net margin impact",
                   "Where to pilot"]},
    {"key": "promotion", "label": "Run a promotion",
     "example": "What if we run a 20% weekend offer?",
     "evaluates": ["Expected redemption", "Margin cost", "Break-even incrementality",
                   "Control group requirement"]},
    {"key": "delist", "label": "Remove an item",
     "example": "What if we delist the veg wrap?",
     "evaluates": ["Revenue at risk", "Substitution", "Sole-item baskets",
                   "Operational saving"]},
]


class SimulateRequest(BaseModel):
    scenario_type: str | None = None
    target: str = ""
    magnitude: float = 0.0
    question: str = Field(default="", max_length=600)
    period_days: int = Field(default=30, ge=7, le=365)
    save: bool = True


@router.get("/scenarios")
def scenarios():
    return {"scenarios": SCENARIOS}


@router.post("/run")
def simulate(
    payload: SimulateRequest,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    ctx = AnalysisContext(
        db=db, tenant_id=tenant.id, period_days=payload.period_days,
        period_end=datetime.now(UTC), currency=tenant.currency, vertical=tenant.vertical,
    )

    scenario_type, target, magnitude = payload.scenario_type, payload.target, payload.magnitude
    if payload.question and not scenario_type:
        parsed = parse_question(payload.question, ctx)
        scenario_type = parsed["scenario_type"]
        target = target or parsed["target"]
        magnitude = magnitude or parsed["magnitude"]
    if not scenario_type:
        raise HTTPException(
            status_code=400, detail="Provide either a scenario_type or a question to parse.")

    outcome = run_scenario(ctx, scenario_type, target, magnitude)

    if payload.save:
        run = SimulationRun(
            tenant_id=tenant.id, created_by=principal.user_id,
            scenario_type=scenario_type,
            question=(payload.question or f"{scenario_type}: {target} {magnitude}")[:500],
            parameters=json.dumps({"target": target, "magnitude": magnitude,
                                   "period_days": payload.period_days}),
            results=json.dumps(outcome.get("results", {}), default=str)[:60000],
            narrative=outcome.get("narrative", ""),
            confidence=float(outcome.get("confidence", 0.0)),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        outcome["run_id"] = run.id

    return outcome


@router.get("/runs")
def list_runs(
    limit: int = Query(25, le=100),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(SimulationRun).where(SimulationRun.tenant_id == principal.tenant_id)
        .order_by(SimulationRun.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": r.id, "scenario_type": r.scenario_type, "question": r.question,
            "parameters": json.loads(r.parameters or "{}"),
            "results": json.loads(r.results or "{}"),
            "narrative": r.narrative, "confidence": r.confidence,
            "was_executed": r.was_executed, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.patch("/runs/{run_id}/executed")
def mark_executed(
    run_id: str,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Record that the business actually went ahead — so the simulation can be scored
    against what happened next."""
    run = db.get(SimulationRun, run_id)
    if run is None or run.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    run.was_executed = True
    db.commit()
    return {"id": run.id, "was_executed": True}
