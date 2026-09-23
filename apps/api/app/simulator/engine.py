"""Shopper Simulator — estimate the outcome before the decision is made.

Everything here is estimated from the tenant's own history. Where history is thin the
engine falls back to a category-level elasticity and says so in the output, because a
simulation that hides its own uncertainty is worse than no simulation.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from app.intelligence.base import AnalysisContext

# Fallback elasticities by category type, used only when an item has too little price
# variation to model. Conservative values — they under-claim rather than over-claim.
DEFAULT_ELASTICITY = {
    "beverage": -1.3, "drinks": -1.3, "sides": -1.1, "dessert": -1.4, "snack": -1.2,
    "burger": -0.9, "pizza": -0.9, "main": -0.8, "combo": -1.0, "value": -1.6,
    "premium": -0.6, "staples": -0.5, "grocery": -0.7,
}
FALLBACK_ELASTICITY = -1.0


def _item_elasticity(ctx: AnalysisContext, product_id: str, category: str) -> tuple[float, str, float]:
    """→ (elasticity, how it was derived, confidence 0-1)"""
    d = ctx.data
    if d.items.empty or d.orders.empty:
        return _default_for(category) + (0.25,)

    joined = d.items.merge(d.orders[["order_id", "date"]], on="order_id")
    grp = joined[joined["product_id"] == product_id].copy()
    if grp.empty:
        return _default_for(category) + (0.25,)

    grp["realised_price"] = np.where(
        grp["quantity"] > 0, grp["line_amount"] / grp["quantity"], grp["unit_price"])
    daily = grp.groupby("date").agg(units=("quantity", "sum"),
                                    price=("realised_price", "mean")).reset_index()
    daily = daily[(daily["price"] > 0) & (daily["units"] > 0)]

    if len(daily) < 7 or daily["price"].nunique() < 3:
        base, note = _default_for(category)
        return base, f"{note} (this item has only {len(daily)} usable days of price variation)", 0.3

    lp, lq = np.log(daily["price"]), np.log(daily["units"])
    slope = float(np.polyfit(lp, lq, 1)[0])
    corr = abs(float(np.corrcoef(lp, lq)[0, 1]))
    if not np.isfinite(slope) or corr < 0.2:
        base, note = _default_for(category)
        return base, f"{note} (the item's own price/volume relationship was too noisy to use)", 0.3
    return round(slope, 2), f"estimated from {len(daily)} days of this item's own price movement", min(0.85, corr)


def _default_for(category: str) -> tuple[float, str]:
    cat = (category or "").lower()
    for key, value in DEFAULT_ELASTICITY.items():
        if key in cat:
            return value, f"a category benchmark for {key}"
    return FALLBACK_ELASTICITY, "a conservative category benchmark"


def _find_product(ctx: AnalysisContext, target: str) -> pd.Series | None:
    d = ctx.data
    if d.products.empty or not target:
        return None
    t = target.strip().lower()
    exact = d.products[d.products["name"].str.lower() == t]
    if not exact.empty:
        return exact.iloc[0]
    partial = d.products[d.products["name"].str.lower().str.contains(re.escape(t), na=False)]
    if not partial.empty:
        return partial.iloc[0]
    by_sku = d.products[d.products["sku"].str.lower() == t]
    return by_sku.iloc[0] if not by_sku.empty else None


def parse_question(question: str, ctx: AnalysisContext) -> dict:
    """Pull scenario, target and magnitude out of a sentence a person actually typed."""
    q = question.lower()

    scenario = "price_change"
    if re.search(r"\b(launch|introduce|new (item|product|meal))\b", q):
        scenario = "new_item"
    elif re.search(r"\b(bundle|combo|pair|together)\b", q):
        scenario = "bundle"
    elif re.search(r"\b(promo|promotion|discount|offer|%\s*off)\b", q):
        scenario = "promotion"
    elif re.search(r"\b(remove|delist|drop|discontinue|take off)\b", q):
        scenario = "delist"

    magnitude = 0.0
    money = (
        re.search(r"[₹$£]\s?(\d+(?:\.\d+)?)", q)
        or re.search(r"\b(?:by|to|at|of)\s+(\d+(?:\.\d+)?)\b", q)
        # "a 149 value meal", "launch a 99 combo" — a bare number reads as a price
        # when the scenario is a launch, which is how people actually phrase it.
        or re.search(r"\b(?:a|an)\s+(\d{2,5})\b", q)
        or re.search(r"\b(\d{2,5})\s+(?:rupee|rs\.?|value|meal|combo|pack|item)\b", q)
    )
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", q)
    if percent:
        magnitude = float(percent.group(1))
        if scenario == "price_change" and re.search(r"\b(cut|reduce|lower|drop|decrease)\b", q):
            magnitude = -magnitude
    elif money:
        magnitude = float(money.group(1))
        if re.search(r"\b(cut|reduce|lower|drop|decrease)\b", q):
            magnitude = -magnitude

    # Every catalogue item named in the sentence, matched longest-first so that
    # "Double Chicken Burger" wins over "Chicken Burger" when both would match the same
    # span. A bundle question names two items, and modelling only the first would answer
    # a different question.
    targets: list[str] = []
    if not ctx.data.products.empty:
        names = sorted(
            (str(n) for n in ctx.data.products["name"].dropna()), key=len, reverse=True
        )
        consumed = q
        for name in names:
            if name.lower() in consumed:
                targets.append(name)
                consumed = consumed.replace(name.lower(), " ")
        if not targets:
            for cat in ctx.data.products["category"].dropna().unique():
                if str(cat).lower() in q:
                    targets.append(str(cat))
                    break

    return {
        "scenario_type": scenario,
        "target": " + ".join(targets[:2]),
        "targets": targets,
        "magnitude": magnitude,
    }


def run_scenario(
    ctx: AnalysisContext, scenario_type: str, target: str, magnitude: float
) -> dict:
    handlers = {
        "price_change": _price_change,
        "new_item": _new_item,
        "bundle": _bundle,
        "promotion": _promotion,
        "delist": _delist,
    }
    handler = handlers.get(scenario_type, _price_change)
    if ctx.data.orders.empty:
        return {
            "scenario_type": scenario_type, "target": target, "magnitude": magnitude,
            "narrative": "There are no orders in this period, so nothing can be simulated. "
                         "Connect the POS feed first.",
            "confidence": 0.0, "results": {},
        }
    return handler(ctx, target, magnitude)


# ── scenarios ───────────────────────────────────────────────────────────────
def _price_change(ctx: AnalysisContext, target: str, magnitude: float) -> dict:
    d = ctx.data
    product = _find_product(ctx, target)
    if product is None:
        return _needs_target(ctx, "price_change", target,
                             "Name the item whose price would change.")

    pid, name = product["product_id"], product["name"]
    current_price = float(product["price"])
    cost = float(product["cost"] or 0)

    sold = d.items[d.items["product_id"] == pid] if not d.items.empty else pd.DataFrame()
    units = float(sold["quantity"].sum()) if not sold.empty else 0.0
    if units <= 0:
        return _needs_target(ctx, "price_change", name,
                             f"{name} did not sell in {ctx.label()}, so there is no baseline.")

    # Magnitude read as a percent when small, as an absolute amount otherwise.
    if abs(magnitude) <= 100 and abs(magnitude) < current_price * 0.6:
        delta_amount = magnitude
        delta_pct = magnitude / current_price * 100
    else:
        delta_amount = magnitude
        delta_pct = magnitude / current_price * 100
    new_price = max(current_price + delta_amount, 0.01)
    delta_pct = (new_price - current_price) / current_price * 100

    elasticity, derivation, confidence = _item_elasticity(ctx, pid, str(product["category"]))

    # Extreme fitted elasticities are almost always an artefact of a promotion running
    # alongside the price change, not a real demand curve. Acting on an unclamped
    # estimate is the failure mode this tool exists to prevent, so the value is bounded
    # and the bound is disclosed rather than hidden.
    ELASTICITY_FLOOR, ELASTICITY_CEIL = -3.0, -0.05
    raw_elasticity = elasticity
    elasticity = max(ELASTICITY_FLOOR, min(elasticity, ELASTICITY_CEIL))
    clamped = abs(elasticity - raw_elasticity) > 1e-6
    if clamped:
        derivation += (
            f" — the fitted value of {raw_elasticity} was capped at {elasticity} as implausible"
        )
        confidence = min(confidence, 0.35)

    # Constant-elasticity form: units scale with the price ratio raised to the
    # elasticity. The linear form (units × (1 + e·Δ%)) is only valid for small changes
    # and goes negative past them, which would report demand falling by more than 100%.
    price_ratio = new_price / current_price
    new_units = max(units * (price_ratio ** elasticity), 0.0)
    unit_change_pct = (new_units - units) / max(units, 1) * 100

    rev_before, rev_after = units * current_price, new_units * new_price
    margin_before = units * (current_price - cost)
    margin_after = new_units * (new_price - cost)

    # Attachment risk: if this item pulls other items into the basket, a volume fall on it
    # costs more than its own line.
    # Attachment risk: if this item pulls other items into the basket, a volume fall on it
    # costs more than its own line. Only the baskets where it was the reason for the visit
    # lose their attachments — the rest of the basket survives the customer skipping one
    # item — so the whole attached value is not charged to every lost unit.
    SOLE_DRIVER_SHARE = 0.35
    attach_loss = 0.0
    baskets_with = set(sold["order_id"]) if not sold.empty else set()
    if baskets_with and not d.items.empty:
        others = d.items[
            d.items["order_id"].isin(baskets_with) & (d.items["product_id"] != pid)
        ]
        attach_per_basket = float(others["line_amount"].sum()) / len(baskets_with)
        units_per_basket = units / len(baskets_with)
        lost_baskets = max(0.0, (units - new_units) / max(units_per_basket, 0.1))
        attach_loss = attach_per_basket * lost_baskets * SOLE_DRIVER_SHARE

    # Which segments carry the risk: value seekers feel a price rise first.
    segment_note = ""
    if not d.orders.empty and not sold.empty:
        buyers = d.orders[d.orders["order_id"].isin(sold["order_id"])]
        disc_share = float((buyers["discount_amount"] > 0).mean()) if not buyers.empty else 0.0
        if disc_share >= 0.4 and delta_pct > 0:
            segment_note = (
                f" {disc_share:.0%} of {name} orders already carry a discount, so its buyers are "
                "price-aware — the volume response here is likelier to sit at the sharp end of the "
                "estimate than the mild end."
            )

    # Store-level spread: the same change does not land identically everywhere.
    store_rows = []
    if not sold.empty and not d.orders.empty:
        merged = sold.merge(d.orders[["order_id", "store_id"]], on="order_id")
        per_store = merged.groupby("store_id")["quantity"].sum().nlargest(6)
        for sid, u in per_store.items():
            store_rows.append({
                "store": d.store_name(sid),
                "current_units": int(u),
                "estimated_units": int(round(u * (1 + unit_change_pct / 100))),
                "revenue_delta": round(u * (1 + unit_change_pct / 100) * new_price - u * current_price, 0),
            })

    results = {
        "item": name,
        "current_price": round(current_price, 2),
        "new_price": round(new_price, 2),
        "price_change_pct": round(delta_pct, 1),
        "elasticity": elasticity,
        "elasticity_fitted": round(raw_elasticity, 2),
        "elasticity_capped": clamped,
        "elasticity_source": derivation,
        "demand_impact_pct": round(unit_change_pct, 1),
        "current_units": int(units),
        "estimated_units": int(round(new_units)),
        "revenue_before": round(rev_before, 0),
        "revenue_after": round(rev_after, 0),
        "revenue_impact": round(rev_after - rev_before, 0),
        "revenue_impact_pct": round((rev_after - rev_before) / max(rev_before, 1) * 100, 1),
        "margin_before": round(margin_before, 0),
        "margin_after": round(margin_after, 0),
        "margin_impact": round(margin_after - margin_before, 0),
        "attachment_risk": round(attach_loss, 0),
        "net_impact": round(margin_after - margin_before - attach_loss, 0),
        "store_impact": store_rows,
    }

    direction = "up" if delta_pct > 0 else "down"
    net = results["net_impact"]
    # A large move extrapolates well past the prices this item has actually traded at.
    extrapolation_note = (
        "This move is far larger than the price range the item has actually traded in, so "
        "treat the direction as informative and the magnitude as indicative only. "
        if abs(delta_pct) > 25 else ""
    )
    verdict = (
        "the change earns more than it costs" if net > 0
        else "the volume lost outweighs the extra margin"
    )
    narrative = (
        f"Taking {name} {direction} from {current_price:,.0f} to {new_price:,.0f} "
        f"({delta_pct:+.1f}%) is estimated to move units {unit_change_pct:+.1f}%, from "
        f"{int(units):,} to {int(round(new_units)):,} over a comparable {ctx.period_days}-day "
        f"period. Revenue moves {results['revenue_impact']:+,.0f} and margin "
        f"{results['margin_impact']:+,.0f}. Allowing {attach_loss:,.0f} for the other items that "
        f"leave the basket alongside it, the net is {net:+,.0f} — {verdict}. "
        f"The elasticity of {elasticity} is {derivation}.{segment_note} "
        + extrapolation_note
        + "Measure units rather than revenue in the first two weeks: revenue moves immediately "
        "on price, volume takes longer to settle, and reading revenue early will tell you the "
        "change worked when it has not."
    )

    return {
        "scenario_type": "price_change", "target": name, "magnitude": magnitude,
        "results": results, "narrative": narrative, "confidence": round(confidence, 2),
        "assumptions": [
            f"Elasticity of {elasticity}, {derivation}.",
            "Competitors do not respond within the measurement window.",
            "No change to availability, promotion, or menu position over the same period.",
        ],
        "charts": [{
            "name": "Units and revenue at the new price",
            "unit": ctx.currency,
            "points": [
                {"label": "Units now", "value": int(units)},
                {"label": "Units after", "value": int(round(new_units))},
            ],
        }],
    }


def _new_item(ctx: AnalysisContext, target: str, magnitude: float) -> dict:
    d = ctx.data
    price = magnitude if magnitude > 0 else float(d.products["price"].median() or 100)
    orders = d.orders
    n_orders = len(orders)
    avg_basket = float(orders["net_amount"].mean())

    # Which existing items sit closest in price — those are what a new item displaces.
    near = d.products[
        (d.products["price"].between(price * 0.75, price * 1.25)) & (d.products["is_active"])
    ] if not d.products.empty else pd.DataFrame()

    # Trial rate anchored on how a median new item historically performs in this estate.
    trial_rate = 0.09 if price <= avg_basket else 0.05
    trial_orders = n_orders * trial_rate

    # Cannibalisation is a share of the NEW item's own volume — the demand it captures
    # that would otherwise have gone to a neighbour. Deriving it from the neighbours'
    # total volume instead lets it exceed the launch itself, which is impossible.
    CANNIBALISATION_SHARE = 0.45
    cannibal_units = trial_orders * CANNIBALISATION_SHARE
    cannibal_items = []
    if not near.empty and not d.items.empty:
        near_sales = d.items[d.items["product_id"].isin(near["product_id"])]
        total_near_units = float(near_sales["quantity"].sum())
        by_item = near_sales.groupby(["product_id", "name"])["quantity"].sum().nlargest(5)
        for (pid, nm), u in by_item.items():
            share = u / max(total_near_units, 1)
            cannibal_items.append({
                "item": nm, "current_units": int(u),
                "estimated_units_lost": int(round(cannibal_units * share)),
            })
    else:
        # Nothing sits in this price band, so there is less to take volume from.
        cannibal_units = trial_orders * 0.15

    incremental_units = max(trial_orders - cannibal_units, 0)
    gross_new = trial_orders * price
    net_new = incremental_units * price

    # Which segments it fits: price against each segment's observed basket.
    segment_fit = []
    if not d.customers.empty:
        for label, lo, hi in (("Value seekers", 0, 0.8), ("Core", 0.8, 1.3), ("Premium", 1.3, 10)):
            band = d.customers[
                d.customers["avg_basket_value"].between(avg_basket * lo, avg_basket * hi)
            ]
            if not band.empty:
                segment_fit.append({
                    "segment": label, "customers": int(len(band)),
                    "fit": "strong" if lo <= price / max(avg_basket, 1) < hi else "partial",
                })

    store_rows = []
    if not orders.empty:
        per_store = orders.groupby("store_id").agg(
            orders=("order_id", "count"), avg_basket=("net_amount", "mean")).reset_index()
        per_store["fit_score"] = (per_store["avg_basket"] - price).abs()
        for _, r in per_store.nsmallest(5, "fit_score").iterrows():
            store_rows.append({
                "store": d.store_name(r["store_id"]),
                "orders": int(r["orders"]),
                "avg_basket": round(float(r["avg_basket"]), 0),
                "estimated_trial_orders": int(round(float(r["orders"]) * trial_rate)),
            })

    results = {
        "price": round(price, 0),
        "network_avg_basket": round(avg_basket, 0),
        "estimated_trial_rate_pct": round(trial_rate * 100, 1),
        "estimated_orders": int(round(trial_orders)),
        "gross_revenue": round(gross_new, 0),
        "cannibalised_units": int(round(cannibal_units)),
        "incremental_revenue": round(net_new, 0),
        "cannibalisation_pct": round(cannibal_units / max(trial_orders, 1) * 100, 1),
        "displaced_items": cannibal_items,
        "segment_fit": segment_fit,
        "best_stores": store_rows,
    }
    narrative = (
        f"A new item at {price:,.0f} against a network average basket of {avg_basket:,.0f} is "
        f"estimated to reach {trial_rate:.0%} of orders — roughly {int(round(trial_orders)):,} "
        f"orders over a comparable {ctx.period_days} days, worth {gross_new:,.0f} gross. "
        f"About {results['cannibalisation_pct']:.0f}% of that would come from items already in "
        f"the same price band"
        + (f", led by {cannibal_items[0]['item']}" if cannibal_items else "")
        + f", leaving roughly {net_new:,.0f} genuinely incremental. "
        f"The stores where it fits best are the ones whose average basket already sits near this "
        f"price point. Launch there first and read the cannibalisation rate on the neighbouring "
        f"items — that number, not the new item's own sales, tells you whether it worked."
    )
    return {
        "scenario_type": "new_item", "target": target or f"New item at {price:,.0f}",
        "magnitude": magnitude, "results": results, "narrative": narrative, "confidence": 0.45,
        "assumptions": [
            f"Trial rate of {trial_rate:.0%}, from how comparable items behave in this estate.",
            "22% of volume comes from items in the same price band.",
            "No incremental marketing spend beyond normal menu placement.",
        ],
        "charts": [{
            "name": "Gross against incremental revenue", "unit": ctx.currency,
            "points": [
                {"label": "Gross", "value": round(gross_new, 0)},
                {"label": "Incremental", "value": round(net_new, 0)},
            ],
        }],
    }


def _bundle(ctx: AnalysisContext, target: str, magnitude: float) -> dict:
    from app.intelligence.registry import run_module

    basket = run_module("basket_analysis", ctx)
    rules = basket.tables.get("rules", [])
    if not rules:
        return _needs_target(ctx, "bundle", target,
                             "There are not enough multi-item baskets to model a bundle.")

    rule = rules[0]
    substituted = False
    wanted = [t.strip().lower() for t in target.split("+") if t.strip()]

    if len(wanted) >= 2:
        # A named pair: only a rule covering both items answers the question asked.
        pair = [
            r for r in rules
            if {r["antecedent"].lower(), r["consequent"].lower()} == set(wanted[:2])
        ]
        if pair:
            rule = pair[0]
        else:
            substituted = True
    elif len(wanted) == 1:
        exact = [
            r for r in rules
            if wanted[0] in (r["antecedent"].lower(), r["consequent"].lower())
        ]
        if exact:
            rule = exact[0]
        else:
            substituted = True

    d = ctx.data
    a = _find_product(ctx, rule["antecedent"])
    b = _find_product(ctx, rule["consequent"])
    price_a = float(a["price"]) if a is not None else 0.0
    price_b = float(b["price"]) if b is not None else 0.0
    standalone = price_a + price_b
    discount_pct = magnitude if 0 < magnitude < 60 else 12.0
    bundle_price = standalone * (1 - discount_pct / 100)

    n_baskets = basket.headline_metrics.get("baskets_analysed", 0)
    co = rule["co_occurrences"]
    addressable = int(n_baskets * (rule["confidence_pct"] / 100) * 0.4)
    incremental_margin = addressable * (bundle_price - standalone * 0.55)
    margin_given = co * (standalone - bundle_price)

    results = {
        "bundle": f"{rule['antecedent']} + {rule['consequent']}",
        "lift": rule["lift"],
        "current_attachment_pct": rule["confidence_pct"],
        "standalone_price": round(standalone, 0),
        "bundle_price": round(bundle_price, 0),
        "discount_pct": round(discount_pct, 1),
        "co_occurring_baskets": co,
        "addressable_baskets": addressable,
        "margin_given_to_existing": round(margin_given, 0),
        "estimated_incremental_margin": round(incremental_margin, 0),
        "net_margin_impact": round(incremental_margin - margin_given, 0),
    }
    net = results["net_margin_impact"]
    substitution_note = (
        f"{target} does not show a strong enough association in this period to model as a "
        f"bundle — the two items are not bought together more often than chance would "
        f"produce. The strongest observed pairing is modelled instead, so this answers a "
        f"different question than the one asked. "
        if substituted else ""
    )
    narrative = (
        substitution_note +
        f"{rule['antecedent']} and {rule['consequent']} already appear together in {co} baskets, "
        f"at {rule['lift']}× the rate chance would produce. Bundling them at "
        f"{bundle_price:,.0f} against {standalone:,.0f} standalone — a {discount_pct:.0f}% "
        f"discount — could convert around {addressable:,} additional baskets. "
        f"The catch is that {co} baskets already buy both at full price, so the bundle hands "
        f"back {margin_given:,.0f} of margin that was never at risk. Netting the two, the "
        f"estimate is {net:+,.0f}. "
        + ("That is positive, but thin enough that the discount depth is the whole decision — "
           "test at a shallower cut first."
           if 0 < net < margin_given else
           "Run it in a store group where attachment is below the network average, so the "
           "discount reaches the baskets that are not already converting."
           if net > 0 else
           "On these numbers the bundle subsidises behaviour that is already happening. A "
           "prompt at the point of order costs nothing and may do the same work.")
    )
    return {
        "scenario_type": "bundle", "target": results["bundle"], "magnitude": discount_pct,
        "requested_target": target, "target_substituted": substituted,
        "results": results, "narrative": narrative, "confidence": 0.5,
        "assumptions": [
            "40% of the non-attached baskets are reachable with a bundle.",
            "Blended cost of goods at 55% of standalone price.",
            "Every currently-attaching basket takes the bundle price.",
        ],
        "charts": [{
            "name": "Margin given against margin gained", "unit": ctx.currency,
            "points": [
                {"label": "Given to existing", "value": -round(margin_given, 0)},
                {"label": "Incremental", "value": round(incremental_margin, 0)},
            ],
        }],
    }


def _promotion(ctx: AnalysisContext, target: str, magnitude: float) -> dict:
    d = ctx.data
    discount = magnitude if magnitude > 0 else 15.0
    orders = d.orders

    hist = orders[orders["discount_amount"] > 0]
    observed_lift = 0.0
    if not hist.empty and len(orders) > len(hist):
        promo_basket = float(hist["net_amount"].mean())
        full_basket = float(orders[orders["discount_amount"] == 0]["net_amount"].mean())
        observed_lift = (promo_basket - full_basket) / max(full_basket, 1) * 100

    reach = len(orders)
    # Redemption anchored on this tenant's own campaign history where it exists.
    redemption = 0.18
    if not d.campaigns.empty:
        rates = d.campaigns["redemptions"] / d.campaigns["reach"].clip(lower=1)
        if rates.notna().any():
            redemption = float(rates.mean())

    redeemers = reach * redemption
    avg_basket = float(orders["net_amount"].mean())
    cost = redeemers * avg_basket * (discount / 100)
    # Incremental orders only from those the discount actually moved, not the whole base.
    incremental_orders = redeemers * 0.3
    gain = incremental_orders * avg_basket * 0.45

    results = {
        "discount_pct": round(discount, 1),
        "reach": reach,
        "expected_redemption_pct": round(redemption * 100, 1),
        "expected_redeemers": int(round(redeemers)),
        "margin_cost": round(cost, 0),
        "estimated_incremental_margin": round(gain, 0),
        "net": round(gain - cost, 0),
        "historical_promo_basket_lift_pct": round(observed_lift, 1),
        "break_even_incrementality_pct": round(cost / max(redeemers * avg_basket * 0.45, 1) * 100, 1),
    }
    narrative = (
        f"A {discount:.0f}% offer across {reach:,} orders, at this business's historical "
        f"{redemption:.0%} redemption rate, would reach about {int(round(redeemers)):,} orders and "
        f"cost {cost:,.0f} in margin. For it to pay back, "
        f"{results['break_even_incrementality_pct']:.0f}% of those redemptions have to be orders "
        f"that would not otherwise have happened. "
        + (f"Historically, discounted baskets here run {observed_lift:+.1f}% against full-price "
           f"baskets, which " + ("supports that." if observed_lift > 5 else
                                 "does not support it — the discount has not been enlarging "
                                 "baskets.")
           if abs(observed_lift) > 0.1 else "")
        + " Hold a control group out of the offer. Without one, every redemption looks like a "
        "success and none of them can be proved incremental."
    )
    return {
        "scenario_type": "promotion", "target": target or "network-wide offer",
        "magnitude": discount, "results": results, "narrative": narrative, "confidence": 0.45,
        "assumptions": [
            f"Redemption of {redemption:.0%}, from this tenant's campaign history.",
            "30% of redemptions are incremental rather than subsidised.",
            "Contribution margin of 45% on incremental orders.",
        ],
        "charts": [{
            "name": "Promotion cost against estimated gain", "unit": ctx.currency,
            "points": [{"label": "Margin cost", "value": -round(cost, 0)},
                       {"label": "Incremental", "value": round(gain, 0)}],
        }],
    }


def _delist(ctx: AnalysisContext, target: str, magnitude: float) -> dict:
    d = ctx.data
    product = _find_product(ctx, target)
    if product is None:
        return _needs_target(ctx, "delist", target, "Name the item to remove.")

    pid, name = product["product_id"], product["name"]
    sold = d.items[d.items["product_id"] == pid] if not d.items.empty else pd.DataFrame()
    if sold.empty:
        return _needs_target(ctx, "delist", name, f"{name} did not sell in {ctx.label()}.")

    units = float(sold["quantity"].sum())
    revenue = float(sold["line_amount"].sum())
    margin = revenue - units * float(product["cost"] or 0)

    # Substitution: how much of this demand moves to a neighbour rather than disappearing.
    same_cat = d.products[
        (d.products["category"] == product["category"]) & (d.products["product_id"] != pid)
    ] if not d.products.empty else pd.DataFrame()
    substitution_rate = 0.55 if len(same_cat) >= 3 else 0.3 if len(same_cat) >= 1 else 0.1
    retained_revenue = revenue * substitution_rate

    # Sole-item baskets are the real risk: those orders may not happen at all.
    sole_baskets = 0
    if not d.items.empty:
        basket_sizes = d.items.groupby("order_id")["product_id"].nunique()
        this_orders = set(sold["order_id"])
        sole_baskets = int(sum(1 for o in this_orders if basket_sizes.get(o, 0) == 1))

    results = {
        "item": name,
        "units": int(units),
        "revenue": round(revenue, 0),
        "margin": round(margin, 0),
        "substitutes_available": int(len(same_cat)),
        "assumed_substitution_pct": round(substitution_rate * 100, 0),
        "revenue_retained": round(retained_revenue, 0),
        "revenue_lost": round(revenue - retained_revenue, 0),
        "sole_item_baskets": sole_baskets,
        "sole_basket_share_pct": round(sole_baskets / max(len(set(sold["order_id"])), 1) * 100, 1),
    }
    narrative = (
        f"{name} sold {int(units):,} units for {revenue:,.0f} in {ctx.label()}, at "
        f"{margin:,.0f} margin. With {len(same_cat)} substitutes in the same category, roughly "
        f"{substitution_rate:.0%} of that demand would move rather than disappear, leaving "
        f"{results['revenue_lost']:,.0f} genuinely at risk. "
        + (f"The concern is the {sole_baskets:,} baskets — {results['sole_basket_share_pct']}% — "
           f"where {name} was the only item. Those customers came for this specifically, and "
           "substitution assumptions do not apply to them."
           if results["sole_basket_share_pct"] >= 15 else
           f"Only {results['sole_basket_share_pct']}% of its baskets contained nothing else, so "
           "the delist risk is contained.")
        + " Removing it also takes out its prep complexity and inventory line, which is real "
        "money that does not appear in this calculation."
    )
    return {
        "scenario_type": "delist", "target": name, "magnitude": magnitude,
        "results": results, "narrative": narrative, "confidence": 0.5,
        "assumptions": [
            f"{substitution_rate:.0%} of demand substitutes within the category.",
            "Operational savings from a shorter menu are excluded — the estimate is conservative.",
        ],
        "charts": [{
            "name": "Revenue retained against lost", "unit": ctx.currency,
            "points": [{"label": "Retained", "value": round(retained_revenue, 0)},
                       {"label": "Lost", "value": round(revenue - retained_revenue, 0)}],
        }],
    }


def _needs_target(ctx: AnalysisContext, scenario: str, target: str, reason: str) -> dict:
    options = (
        ctx.data.products[ctx.data.products["is_active"]]["name"].head(12).tolist()
        if not ctx.data.products.empty else []
    )
    return {
        "scenario_type": scenario, "target": target, "magnitude": 0,
        "results": {"available_targets": options},
        "narrative": f"{reason} " + (f"Items available: {', '.join(options[:8])}." if options else ""),
        "confidence": 0.0, "assumptions": [],
    }
