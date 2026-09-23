"""The simulator must not produce numbers that cannot happen."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.intelligence.base import AnalysisContext
from app.models.tenant import Tenant
from app.simulator.engine import parse_question, run_scenario


@pytest.fixture
def ctx(seeded_tenant: Tenant, db) -> AnalysisContext:
    return AnalysisContext(
        db=db, tenant_id=seeded_tenant.id, period_days=30,
        period_end=datetime.now(UTC), currency="INR", vertical="qsr",
    )


def test_price_rise_cannot_lose_more_than_all_demand(ctx: AnalysisContext):
    """The linear elasticity form goes below −100%; the constant-elasticity form cannot."""
    out = run_scenario(ctx, "price_change", "Cola 400ml", 40)
    results = out["results"]
    if "demand_impact_pct" in results:
        assert results["demand_impact_pct"] > -100
        assert results["estimated_units"] >= 0


def test_extreme_elasticity_is_capped_and_disclosed(ctx: AnalysisContext):
    out = run_scenario(ctx, "price_change", "Cola 400ml", 20)
    results = out["results"]
    if "elasticity" in results:
        assert -3.0 <= results["elasticity"] <= -0.05
        if results.get("elasticity_capped"):
            # A capped estimate must say so, and must not claim high confidence.
            assert "capped" in results["elasticity_source"]
            assert out["confidence"] <= 0.35


def test_new_item_cannibalisation_stays_within_its_own_volume(ctx: AnalysisContext):
    out = run_scenario(ctx, "new_item", "", 149)
    results = out["results"]
    assert 0 <= results["cannibalisation_pct"] <= 100
    assert results["incremental_revenue"] <= results["gross_revenue"]


def test_bundle_declares_when_it_answers_a_different_question(ctx: AnalysisContext):
    """Silently modelling a pair the user did not name is worse than saying no."""
    out = run_scenario(ctx, "bundle", "Nonexistent Item", 15)
    if out.get("target_substituted"):
        assert "different question" in out["narrative"]


def test_missing_target_does_not_invent_one(ctx: AnalysisContext):
    out = run_scenario(ctx, "price_change", "A Product That Does Not Exist", 10)
    assert out["confidence"] == 0.0
    assert not out["results"].get("revenue_impact")


def test_question_parsing_finds_both_items_in_a_bundle(ctx: AnalysisContext):
    parsed = parse_question(
        "what if we bundle Chicken Burger with French Fries (Regular) at 15% off?", ctx
    )
    assert parsed["scenario_type"] == "bundle"
    assert parsed["magnitude"] == 15
    assert len(parsed["targets"]) >= 2


def test_bare_price_is_read_as_a_price(ctx: AnalysisContext):
    parsed = parse_question("what if we launch a 149 value meal?", ctx)
    assert parsed["scenario_type"] == "new_item"
    assert parsed["magnitude"] == 149
