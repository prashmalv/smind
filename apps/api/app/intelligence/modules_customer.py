"""Modules that answer *who is buying* and *what should we offer them next*.

customer_profiling · purchase_behavior · churn_intelligence · next_best_offer
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.intelligence.base import (
    Action,
    AnalysisContext,
    Finding,
    IntelligenceModule,
    ModuleResult,
    Series,
)
from app.intelligence.segments import SEGMENTS, response_for


def _rfm(customers: pd.DataFrame, orders: pd.DataFrame, now) -> pd.DataFrame:
    """Recency / frequency / monetary, computed from the period's orders."""
    if orders.empty:
        return pd.DataFrame()
    agg = (
        orders.dropna(subset=["customer_id"])
        .groupby("customer_id")
        .agg(
            frequency=("order_id", "count"),
            monetary=("net_amount", "sum"),
            avg_basket=("net_amount", "mean"),
            last_seen=("placed_at", "max"),
            first_seen=("placed_at", "min"),
            items=("item_count", "sum"),
        )
        .reset_index()
    )
    agg["recency_days"] = (pd.Timestamp(now) - agg["last_seen"]).dt.days
    agg["tenure_days"] = (agg["last_seen"] - agg["first_seen"]).dt.days.clip(lower=0)
    if not customers.empty:
        agg = agg.merge(
            customers[["customer_id", "age_band", "gender", "city", "order_count",
                       "lifetime_value", "last_order_at"]],
            on="customer_id", how="left",
        )
    return agg


def assign_segment(row: pd.Series, thresholds: dict[str, float]) -> tuple[str, str]:
    """Rules first, because a marketing head has to be able to argue with the answer.

    Ordering matters: lapsed beats everything (they are not buying at all), then premium,
    then frequency, then the behavioural flavours.
    """
    recency = row.get("recency_days", 999)
    freq = row.get("frequency", 0)
    basket = row.get("avg_basket", 0.0)
    discount_share = row.get("discount_share", 0.0)
    delivery_share = row.get("delivery_share", 0.0)
    top_product_share = row.get("top_product_share", 0.0)

    if recency > thresholds["lapsed_days"]:
        return "lapsed_customers", f"No order in {int(recency)} days"
    if basket >= thresholds["premium_basket"] and freq >= 2:
        return "premium_customers", f"Average basket {basket:,.0f} is in the top quartile"
    if freq >= thresholds["high_frequency"]:
        return "frequency_customers", f"{int(freq)} orders in the period"
    if discount_share >= 0.5:
        return "value_seekers", f"{discount_share:.0%} of orders carried a discount"
    if delivery_share >= 0.6:
        return "convenience_seekers", f"{delivery_share:.0%} of orders were delivery or takeaway"
    if top_product_share >= 0.5 and freq >= 2:
        return "product_loyalists", f"{top_product_share:.0%} of spend on one product"
    return "occasional_customers", f"{int(freq)} order(s), last seen {int(recency)} days ago"


class CustomerProfilingModule(IntelligenceModule):
    key = "customer_profiling"
    title = "Customer profiling"
    question = "Who is buying?"
    business_output = "Customer segments"
    reads = "Age group, location, visit frequency, order value, preferences"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.orders.empty:
            return self.empty("No orders in this period, so no profile can be built.")

        rfm = _rfm(d.customers, d.orders, ctx.period_end)
        if rfm.empty:
            return self.empty("Orders in this period carry no customer identifier.")

        # Behavioural shares that drive the value/convenience/loyalist rules.
        o = d.orders.dropna(subset=["customer_id"]).copy()
        o["discounted"] = (o["discount_amount"] > 0).astype(int)
        o["remote"] = o["channel"].isin(["delivery", "takeaway", "online"]).astype(int)
        shares = o.groupby("customer_id").agg(
            discount_share=("discounted", "mean"), delivery_share=("remote", "mean")
        ).reset_index()
        rfm = rfm.merge(shares, on="customer_id", how="left").fillna(
            {"discount_share": 0.0, "delivery_share": 0.0}
        )

        if not d.items.empty:
            spend = d.items.merge(o[["order_id", "customer_id"]], on="order_id", how="inner")
            per_cust = spend.groupby("customer_id")["line_amount"].sum()
            top = spend.groupby(["customer_id", "product_id"])["line_amount"].sum().reset_index()
            top = top.loc[top.groupby("customer_id")["line_amount"].idxmax()]
            top["top_product_share"] = top["line_amount"] / top["customer_id"].map(per_cust)
            rfm = rfm.merge(
                top[["customer_id", "product_id", "top_product_share"]], on="customer_id", how="left"
            )
        rfm["top_product_share"] = rfm.get("top_product_share", pd.Series(dtype=float)).fillna(0.0)

        thresholds = {
            "lapsed_days": max(21, int(rfm["recency_days"].quantile(0.85))),
            "premium_basket": float(rfm["avg_basket"].quantile(0.75)),
            "high_frequency": max(3, int(rfm["frequency"].quantile(0.8))),
        }
        assigned = rfm.apply(lambda r: assign_segment(r, thresholds), axis=1, result_type="expand")
        rfm["segment_key"] = assigned[0]
        rfm["rationale"] = assigned[1]

        counts = rfm["segment_key"].value_counts()
        value = rfm.groupby("segment_key")["monetary"].sum()
        total_value = float(value.sum()) or 1.0

        rows = []
        for seg in SEGMENTS:
            n = int(counts.get(seg.key, 0))
            v = float(value.get(seg.key, 0.0))
            rows.append({
                "segment": seg.label,
                "segment_key": seg.key,
                "customers": n,
                "share_pct": round(n / max(len(rfm), 1) * 100, 1),
                "revenue": round(v, 0),
                "revenue_share_pct": round(v / total_value * 100, 1),
                "avg_basket": round(
                    float(rfm[rfm["segment_key"] == seg.key]["avg_basket"].mean() or 0), 0
                ),
                "who": seg.who,
                "respond_with": seg.respond_with,
            })

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "active_customers": int(len(rfm)),
                "avg_basket": round(float(rfm["avg_basket"].mean()), 0),
                "avg_frequency": round(float(rfm["frequency"].mean()), 2),
                "segments_in_play": int((counts > 0).sum()),
            },
            series=[Series(
                name="Customers by segment",
                points=[{"label": r["segment"], "value": r["customers"]} for r in rows if r["customers"]],
                unit="customers",
            )],
            tables={"segments": rows, "thresholds": [
                {"rule": "Lapsed after", "value": f"{thresholds['lapsed_days']} days"},
                {"rule": "Premium basket above", "value": f"{thresholds['premium_basket']:,.0f}"},
                {"rule": "High frequency at", "value": f"{thresholds['high_frequency']} orders"},
            ]},
        )

        # ── findings ────────────────────────────────────────────────────────
        concentrated = max(rows, key=lambda r: r["revenue_share_pct"])
        if concentrated["revenue_share_pct"] >= 35 and concentrated["customers"] > 0:
            result.findings.append(Finding(
                headline=(
                    f"{concentrated['revenue_share_pct']}% of revenue comes from "
                    f"{concentrated['segment'].lower()}, who are "
                    f"{concentrated['share_pct']}% of customers."
                ),
                reasoning=(
                    f"{concentrated['customers']} customers in this segment spent "
                    f"{self.money(concentrated['revenue'], ctx.currency)} in {ctx.label()}, at an "
                    f"average basket of {self.money(concentrated['avg_basket'], ctx.currency)}. "
                    "Revenue concentrated in a narrow segment is fragile: a change in that "
                    "group's behaviour moves the whole number."
                ),
                actions=[
                    Action(f"Protect this base with {concentrated['respond_with'].lower()}.",
                           owner="marketing", effort="low", horizon="this week",
                           expected_impact="Retains the revenue already in hand"),
                    Action("Run a separate acquisition test aimed at the next segment down, "
                           "to reduce dependence on one group.",
                           owner="marketing", effort="medium", horizon="this quarter"),
                ],
                kind="risk", severity="high", confidence=0.82,
                metric_value=concentrated["revenue_share_pct"],
                evidence={"segment": concentrated["segment"], "rows": rows[:4]},
            ))

        lapsed = next((r for r in rows if r["segment_key"] == "lapsed_customers"), None)
        if lapsed and lapsed["customers"] >= 5:
            recoverable = lapsed["customers"] * lapsed["avg_basket"] * 0.15
            result.findings.append(Finding(
                headline=f"{lapsed['customers']} customers have gone quiet past the "
                         f"{thresholds['lapsed_days']}-day mark.",
                reasoning=(
                    "These customers ordered before and have now stopped. Their historical "
                    f"average basket was {self.money(lapsed['avg_basket'], ctx.currency)}, so the "
                    "lapsed pool represents revenue that has already proven it exists — it is "
                    "cheaper to recover than to acquire."
                ),
                actions=[Action(
                    "Trigger a win-back offer to the lapsed pool, capped at the segment's "
                    "average basket so the discount does not exceed the value recovered.",
                    owner="marketing", effort="low", horizon="this week",
                    expected_impact=f"~{self.money(recoverable, ctx.currency)} at a 15% recovery rate",
                )],
                kind="opportunity", severity="medium", confidence=0.7,
                metric_value=float(lapsed["customers"]), estimated_impact=round(recoverable, 0),
                evidence={"threshold_days": thresholds["lapsed_days"]},
            ))

        result.narrative = (
            f"{len(rfm):,} customers were active in {ctx.label()}, spread across "
            f"{int((counts > 0).sum())} of the seven behavioural segments. "
            f"The largest by revenue is {concentrated['segment'].lower()} at "
            f"{concentrated['revenue_share_pct']}%."
        )
        result.tables["_assignments"] = (
            rfm[["customer_id", "segment_key", "rationale", "monetary", "recency_days"]]
            .to_dict("records")
        )
        return result


class PurchaseBehaviorModule(IntelligenceModule):
    key = "purchase_behavior"
    title = "Purchase behaviour"
    question = "What are they buying?"
    business_output = "Buying patterns"
    reads = "Items, combos, add-ons, time and day, frequency"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.orders.empty:
            return self.empty()

        cur, prior = d.orders, d.prior_orders
        rev, prior_rev = float(cur["net_amount"].sum()), float(prior["net_amount"].sum())
        basket = float(cur["net_amount"].mean())
        prior_basket = float(prior["net_amount"].mean()) if not prior.empty else 0.0

        by_daypart = cur.groupby("daypart").agg(
            orders=("order_id", "count"), revenue=("net_amount", "sum")
        ).reset_index().sort_values("revenue", ascending=False)
        by_dow = cur.groupby("dow").agg(orders=("order_id", "count")).reset_index()
        by_channel = cur.groupby("channel").agg(
            orders=("order_id", "count"), revenue=("net_amount", "sum"),
            avg_basket=("net_amount", "mean"),
        ).reset_index().sort_values("revenue", ascending=False)

        daily = cur.groupby("date").agg(revenue=("net_amount", "sum")).reset_index()

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "orders": int(len(cur)),
                "revenue": round(rev, 0),
                "revenue_delta_pct": self.pct_change(rev, prior_rev),
                "avg_basket": round(basket, 0),
                "basket_delta_pct": self.pct_change(basket, prior_basket),
                "items_per_order": round(float(cur["item_count"].mean()), 2),
            },
            series=[
                Series(name="Daily revenue",
                       points=[{"label": str(r["date"]), "value": round(float(r["revenue"]), 0)}
                               for _, r in daily.iterrows()], unit=ctx.currency),
                Series(name="Orders by daypart",
                       points=[{"label": r["daypart"] or "unspecified", "value": int(r["orders"])}
                               for _, r in by_daypart.iterrows()], unit="orders"),
            ],
            tables={
                "by_daypart": by_daypart.assign(
                    revenue=by_daypart["revenue"].round(0)).to_dict("records"),
                "by_channel": by_channel.assign(
                    revenue=by_channel["revenue"].round(0),
                    avg_basket=by_channel["avg_basket"].round(0)).to_dict("records"),
                "by_day_of_week": by_dow.to_dict("records"),
            },
        )

        rev_delta = self.pct_change(rev, prior_rev)
        if prior_rev > 0 and abs(rev_delta) >= 3:
            # Decompose: did the number of orders move, or the size of each one?
            order_delta = self.pct_change(len(cur), len(prior))
            basket_delta = self.pct_change(basket, prior_basket)
            driver = ("fewer orders" if abs(order_delta) > abs(basket_delta)
                      else "a smaller average basket")
            direction = "declined" if rev_delta < 0 else "grew"
            worst_part = by_daypart.iloc[-1]["daypart"] if len(by_daypart) > 1 else ""
            result.findings.append(Finding(
                headline=f"Revenue {direction} {abs(rev_delta):.1f}% against the prior "
                         f"{ctx.period_days} days.",
                reasoning=(
                    f"Order count moved {order_delta:+.1f}% and average basket moved "
                    f"{basket_delta:+.1f}%, so the change is driven mainly by {driver}. "
                    + (f"The weakest daypart is {worst_part}. " if worst_part else "")
                    + "Splitting volume from basket size matters because the two need different "
                    "responses — traffic problems are a marketing and operations issue, basket "
                    "problems are a merchandising and attachment issue."
                ),
                actions=[
                    Action(
                        "Run an attachment push on the weakest daypart: prompt one add-on at "
                        "the point of order." if driver == "a smaller average basket"
                        else "Put spend behind the weakest daypart to recover order volume before "
                             "touching price.",
                        owner="marketing" if driver == "fewer orders" else "category",
                        effort="low", horizon="this week",
                    ),
                    Action("Re-measure both components in two weeks and record the outcome "
                           "against this insight.", owner="marketing", effort="low",
                           horizon="in two weeks"),
                ],
                kind="anomaly" if abs(rev_delta) >= 7 else "explanation",
                severity="high" if rev_delta <= -7 else "medium",
                confidence=0.85, metric_value=round(rev, 0), metric_delta_pct=rev_delta,
                evidence={"order_delta_pct": order_delta, "basket_delta_pct": basket_delta,
                          "prior_revenue": round(prior_rev, 0)},
            ))

        if len(by_channel) > 1:
            best, worst = by_channel.iloc[0], by_channel.iloc[-1]
            gap = self.pct_change(float(best["avg_basket"]), float(worst["avg_basket"]))
            if gap >= 20:
                result.findings.append(Finding(
                    headline=f"{best['channel'].title()} baskets run {gap:.0f}% larger than "
                             f"{worst['channel']}.",
                    reasoning=(
                        f"Average basket is {self.money(float(best['avg_basket']), ctx.currency)} on "
                        f"{best['channel']} against {self.money(float(worst['avg_basket']), ctx.currency)} "
                        f"on {worst['channel']}. Channel mix therefore changes revenue even when "
                        "customer count is flat."
                    ),
                    actions=[Action(
                        f"Port the attachment prompts that work on {best['channel']} into the "
                        f"{worst['channel']} flow, then compare basket after two weeks.",
                        owner="category", effort="medium", horizon="this month")],
                    kind="opportunity", severity="medium", confidence=0.72,
                    metric_value=round(float(best["avg_basket"]), 0),
                    evidence={"channels": by_channel.head(4).to_dict("records")},
                ))

        result.narrative = (
            f"{len(cur):,} orders worth {self.money(rev, ctx.currency)} in {ctx.label()}, "
            f"averaging {self.money(basket, ctx.currency)} per order "
            f"({rev_delta:+.1f}% on the prior period)."
        )
        return result


class ChurnIntelligenceModule(IntelligenceModule):
    key = "churn_intelligence"
    title = "Churn intelligence"
    question = "What is stopping them?"
    business_output = "Retention triggers"
    reads = "Declining frequency and order behaviour"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.customers.empty:
            return self.empty("No customer records to score.")

        c = d.customers.copy()
        c = c[c["last_order_at"].notna()]
        if c.empty:
            return self.empty("No customer has an order history to score against.")

        now = pd.Timestamp(ctx.period_end)
        c["days_since"] = (now - c["last_order_at"]).dt.days
        c["tenure_days"] = (now - c["first_order_at"]).dt.days.clip(lower=1)
        # Expected gap = how often this customer normally comes back.
        c["expected_gap"] = (c["tenure_days"] / c["order_count"].clip(lower=1)).clip(lower=1)
        c["gap_ratio"] = c["days_since"] / c["expected_gap"]

        # Probability rises with how far past their own rhythm they are, damped by how
        # much history we have — a two-order customer is a weaker signal than a twenty.
        history_weight = (c["order_count"].clip(upper=12) / 12).clip(lower=0.25)
        c["probability"] = (1 - np.exp(-0.55 * (c["gap_ratio"] - 0.8).clip(lower=0))) * history_weight
        c["probability"] = c["probability"].clip(0, 0.97).round(3)
        c["risk_band"] = pd.cut(
            c["probability"], [-0.01, 0.3, 0.6, 1.0], labels=["low", "medium", "high"]
        ).astype(str)
        c["revenue_at_risk"] = (c["lifetime_value"] / c["tenure_days"] * 90 * c["probability"]).round(0)

        def driver(row) -> str:
            if row["gap_ratio"] >= 3:
                return "Far past their normal reorder gap"
            if row["order_count"] <= 2:
                return "Never established a repeat habit"
            if row["avg_basket_value"] < float(c["avg_basket_value"].median()):
                return "Low basket value alongside a widening gap"
            return "Reorder gap widening against their own rhythm"

        c["top_driver"] = c.apply(driver, axis=1)

        # Taken after top_driver exists, so the high-risk table can carry the reason.
        high = c[c["risk_band"] == "high"]
        at_risk_value = float(high["revenue_at_risk"].sum())

        band_counts = c["risk_band"].value_counts()
        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "scored_customers": int(len(c)),
                "high_risk": int(band_counts.get("high", 0)),
                "medium_risk": int(band_counts.get("medium", 0)),
                "revenue_at_risk": round(at_risk_value, 0),
                "avg_expected_gap_days": round(float(c["expected_gap"].median()), 1),
            },
            series=[Series(
                name="Customers by churn risk",
                points=[{"label": b.title(), "value": int(band_counts.get(b, 0))}
                        for b in ("low", "medium", "high")], unit="customers",
            )],
            tables={
                "top_risk": (
                    high.nlargest(25, "revenue_at_risk")[
                        ["customer_id", "probability", "days_since", "expected_gap",
                         "order_count", "lifetime_value", "revenue_at_risk", "top_driver"]
                    ].round(2).to_dict("records")
                ),
                "drivers": c["top_driver"].value_counts().reset_index().rename(
                    columns={"index": "driver", "count": "customers"}).to_dict("records"),
            },
        )

        if len(high) >= 3:
            top_driver = c[c["risk_band"] == "high"]["top_driver"].mode()
            top_driver = str(top_driver.iloc[0]) if not top_driver.empty else "a widening reorder gap"
            result.findings.append(Finding(
                headline=f"{len(high)} customers are at high risk of churning, carrying "
                         f"{self.money(at_risk_value, ctx.currency)} of ninety-day revenue.",
                reasoning=(
                    f"Each customer is scored against their own reorder rhythm rather than a flat "
                    f"cut-off, so a weekly buyer who has been silent fourteen days scores higher "
                    f"than a monthly buyer at the same gap. The dominant driver in this cohort is: "
                    f"{top_driver.lower()}. Median expected gap across the base is "
                    f"{float(c['expected_gap'].median()):.0f} days."
                ),
                actions=[
                    Action("Trigger a personalised win-back to the high-risk band before the gap "
                           "doubles — recovery rates fall sharply after that point.",
                           owner="marketing", effort="low", horizon="this week",
                           expected_impact=f"{self.money(at_risk_value * 0.2, ctx.currency)} at a "
                                           "20% save rate"),
                    Action("Hold a control group out of the win-back so the save rate is "
                           "measurable rather than assumed.",
                           owner="marketing", effort="low", horizon="this week"),
                ],
                kind="risk", severity="high" if len(high) > len(c) * 0.15 else "medium",
                confidence=0.75, metric_value=float(len(high)),
                estimated_impact=round(at_risk_value, 0),
                evidence={"bands": band_counts.to_dict()},
            ))

        result.narrative = (
            f"{int(band_counts.get('high', 0))} of {len(c):,} scored customers sit in the high-risk "
            f"band, representing {self.money(at_risk_value, ctx.currency)} of revenue over the next "
            "ninety days."
        )
        result.tables["_scores"] = c[
            ["customer_id", "probability", "risk_band", "days_since", "expected_gap",
             "top_driver", "revenue_at_risk"]
        ].to_dict("records")
        return result


class NextBestOfferModule(IntelligenceModule):
    key = "next_best_offer"
    title = "Next best offer"
    question = "What should we offer them next?"
    business_output = "Personalised offers"
    reads = "Customer history and context"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.orders.empty or d.items.empty:
            return self.empty("Offers need order history with line items.")

        o = d.orders.dropna(subset=["customer_id"])
        if o.empty:
            return self.empty("Orders in this period are not linked to customers.")

        joined = d.items.merge(o[["order_id", "customer_id", "placed_at"]], on="order_id")

        # What each category attaches to, network-wide — the base rate we compare against.
        baskets = joined.groupby("order_id")["category"].apply(set)
        category_orders = len(baskets)
        attach_rate = {}
        for cat in joined["category"].dropna().unique():
            attach_rate[cat] = sum(1 for b in baskets if cat in b) / max(category_orders, 1)

        cust_cats = joined.groupby("customer_id")["category"].apply(set)
        cust_spend = joined.groupby("customer_id")["line_amount"].sum()
        cust_orders = o.groupby("customer_id")["order_id"].count()
        last_seen = o.groupby("customer_id")["placed_at"].max()
        now = pd.Timestamp(ctx.period_end)

        # Top-selling product in each category, used as the concrete thing to offer.
        top_in_cat = (
            joined.groupby(["category", "product_id", "name"])["line_amount"].sum()
            .reset_index().sort_values("line_amount", ascending=False)
            .drop_duplicates("category").set_index("category")
        )

        offers: list[dict] = []
        for cust, cats in cust_cats.items():
            days_quiet = int((now - last_seen[cust]).days)
            n_orders = int(cust_orders.get(cust, 0))

            # Win-back takes priority: no offer matters if they are not coming back.
            if days_quiet >= 45:
                offers.append({
                    "customer_id": cust, "product_id": None, "offer_type": "winback",
                    "context": f"No order for {days_quiet} days after {n_orders} orders",
                    "inferred_intent": "Lapsing — needs a reason to return, not a bigger basket",
                    "offer_text": "Personalised win-back: their most-ordered item at a "
                                  "time-boxed discount",
                    "propensity": round(min(0.45, 0.5 - days_quiet / 400), 3),
                    "expected_uplift": round(float(cust_spend.get(cust, 0)) / max(n_orders, 1), 0),
                    "channel": "app",
                })
                continue

            # Cross-sell: the category with the widest gap between network attachment and theirs.
            gaps = {c: r for c, r in attach_rate.items() if c not in cats and r >= 0.15}
            if gaps and n_orders >= 2:
                cat = max(gaps, key=gaps.get)
                row = top_in_cat.loc[cat] if cat in top_in_cat.index else None
                avg_basket = float(cust_spend.get(cust, 0)) / max(n_orders, 1)
                offers.append({
                    "customer_id": cust,
                    "product_id": (row["product_id"] if row is not None else None),
                    "offer_type": "cross_sell",
                    "context": f"{n_orders} orders, never bought from {cat}",
                    "inferred_intent": f"Open to {cat.lower()} — {gaps[cat]:.0%} of comparable "
                                       "baskets include it",
                    "offer_text": (
                        f"Add {row['name']} to the next order at an introductory price"
                        if row is not None else f"Introduce {cat} on the next order"
                    ),
                    "propensity": round(min(0.85, gaps[cat] * 1.3), 3),
                    "expected_uplift": round(avg_basket * gaps[cat] * 0.5, 0),
                    "channel": "app",
                })
                continue

            if n_orders >= 4:
                offers.append({
                    "customer_id": cust, "product_id": None, "offer_type": "loyalty",
                    "context": f"{n_orders} orders in {ctx.period_days} days",
                    "inferred_intent": "Habitual — reward the habit rather than discount it",
                    "offer_text": "Tier upgrade with a free item at the next milestone",
                    "propensity": 0.62,
                    "expected_uplift": round(float(cust_spend.get(cust, 0)) * 0.08, 0),
                    "channel": "app",
                })

        offers.sort(key=lambda x: x["propensity"] * max(x["expected_uplift"], 1), reverse=True)
        by_type = pd.Series([o["offer_type"] for o in offers]).value_counts() if offers else pd.Series(dtype=int)
        total_uplift = sum(o["expected_uplift"] * o["propensity"] for o in offers)

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "offers_generated": len(offers),
                "customers_covered": len({o["customer_id"] for o in offers}),
                "expected_uplift": round(total_uplift, 0),
                "avg_propensity": round(
                    float(np.mean([o["propensity"] for o in offers])) if offers else 0.0, 3),
            },
            series=[Series(
                name="Offers by type",
                points=[{"label": k.replace("_", " ").title(), "value": int(v)}
                        for k, v in by_type.items()], unit="offers")],
            tables={"top_offers": offers[:40],
                    "attach_rates": [{"category": k, "network_attach_pct": round(v * 100, 1)}
                                     for k, v in sorted(attach_rate.items(), key=lambda x: -x[1])]},
        )

        if offers:
            top = offers[0]
            cross = [o for o in offers if o["offer_type"] == "cross_sell"]
            if cross:
                cat_counts = pd.Series([o["context"].split("from ")[-1] for o in cross]).value_counts()
                biggest_cat = cat_counts.index[0]
                result.findings.append(Finding(
                    headline=f"{len(cross)} customers buy regularly but have never bought "
                             f"{biggest_cat}.",
                    reasoning=(
                        f"{attach_rate.get(biggest_cat, 0):.0%} of comparable baskets across the "
                        f"network include {biggest_cat}, so the gap is a habit that has not formed "
                        "rather than a stated preference. A record that a customer bought a burger "
                        "is history; the useful part is what they predictably have not tried."
                    ),
                    actions=[Action(
                        f"Push a {biggest_cat.lower()} add-on at the point of order for this list, "
                        "priced as an introduction rather than a discount.",
                        owner="marketing", effort="low", horizon="this week",
                        expected_impact=f"{self.money(sum(o['expected_uplift'] * o['propensity'] for o in cross), ctx.currency)} "
                                        "expected incremental")],
                    kind="opportunity", severity="medium", confidence=0.7,
                    metric_value=float(len(cross)),
                    estimated_impact=round(sum(o["expected_uplift"] * o["propensity"] for o in cross), 0),
                    evidence={"example": top},
                ))

        result.narrative = (
            f"{len(offers):,} offers generated across "
            f"{len({o['customer_id'] for o in offers}):,} customers, with "
            f"{self.money(total_uplift, ctx.currency)} of propensity-weighted uplift."
        )
        result.tables["_offers"] = offers
        return result
