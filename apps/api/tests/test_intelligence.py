"""The contract the whole product rests on.

These do not assert specific numbers — the seeder is random — but they assert the
properties that make the output trustworthy: every module runs, no module reports a
figure without a reason and an action, tenants cannot see each other, and nothing
produces a value that would break JSON.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest

from app.intelligence.base import AnalysisContext
from app.intelligence.registry import MODULES, run_all, run_module, shopper_pulse
from app.models.tenant import Tenant


@pytest.fixture
def ctx(seeded_tenant: Tenant, db) -> AnalysisContext:
    return AnalysisContext(
        db=db, tenant_id=seeded_tenant.id, period_days=30,
        period_end=datetime.now(UTC), currency="INR", vertical="qsr",
    )


def test_every_module_runs(ctx: AnalysisContext):
    results = run_all(ctx)
    assert len(results) == len(MODULES)
    for key, res in results.items():
        assert res.module_key == key
        # A module that cannot complete says so in the coverage note rather than raising.
        assert res.narrative or res.coverage_note, f"{key} returned nothing at all"


@pytest.mark.parametrize("module", [m.key for m in MODULES])
def test_findings_carry_reason_and_action(module: str, ctx: AnalysisContext):
    """The product's whole claim: never a number without a why and a what-to-do."""
    result = run_module(module, ctx)
    for finding in result.findings:
        assert finding.headline.strip(), f"{module}: empty headline"
        assert len(finding.reasoning) > 40, f"{module}: reasoning too thin to be a reason"
        assert finding.actions, f"{module}: a finding with no action is just a dashboard"
        for action in finding.actions:
            assert action.text.strip()
            assert action.owner
        assert 0.0 <= finding.confidence <= 1.0


@pytest.mark.parametrize("module", [m.key for m in MODULES])
def test_output_is_json_serialisable(module: str, ctx: AnalysisContext):
    """pandas emits NaN, which is a legal float and an illegal JSON value."""
    payload = run_module(module, ctx).to_dict()
    encoded = json.dumps(payload)          # raises on NaN via the default encoder
    assert "NaN" not in encoded
    assert "Infinity" not in encoded

    def no_nan(node):
        if isinstance(node, float):
            assert not math.isnan(node) and not math.isinf(node), f"{module} leaked {node}"
        elif isinstance(node, dict):
            for v in node.values():
                no_nan(v)
        elif isinstance(node, list):
            for v in node:
                no_nan(v)

    no_nan(payload)


def test_pulse_signals_are_distinct(ctx: AnalysisContext):
    """Four cards carrying two facts is a worse dashboard than two cards."""
    pulse = shopper_pulse(ctx)
    values = [s["value"] for s in pulse["signals"] if s["value"] not in ("—", "", None)]
    assert len(values) == len(set(values)), f"duplicate signals: {values}"
    assert len(pulse["metrics"]) == 4


def test_pulse_metrics_are_plausible(ctx: AnalysisContext):
    pulse = shopper_pulse(ctx)
    by_label = {m["label"]: m["value"] for m in pulse["metrics"]}
    assert by_label["Active customers"] > 0
    assert by_label["Average basket"] > 0
    # A repeat rate above 100% means the denominator is wrong.
    assert 0 <= by_label["Repeat rate"] <= 100
    assert 0 <= by_label["Customer sentiment"] <= 100


def test_tenant_isolation(seeded_tenant: Tenant, db):
    """A module run for an empty tenant must never see another tenant's rows."""
    other = Tenant(name="Other Co", slug="other-co", vertical="retail", currency="INR")
    db.add(other)
    db.commit()

    empty_ctx = AnalysisContext(
        db=db, tenant_id=other.id, period_days=30, period_end=datetime.now(UTC),
        currency="INR", vertical="retail",
    )
    results = run_all(empty_ctx)
    for key, res in results.items():
        assert not res.findings, f"{key} produced findings for a tenant with no data"
        for value in res.headline_metrics.values():
            if isinstance(value, (int, float)):
                assert value == 0, f"{key} reported {value} for an empty tenant"
