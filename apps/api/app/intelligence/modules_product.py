"""Modules that answer *what are they buying* and *why*, on the catalogue side.

menu_intelligence · basket_analysis · price_sensitivity · trend_detection
"""

from __future__ import annotations

import re
from collections import Counter

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


class MenuIntelligenceModule(IntelligenceModule):
    key = "menu_intelligence"
    title = "Menu intelligence"
    question = "What are they buying?"
    business_output = "Menu optimisation"
    reads = "Best and worst sellers, combinations, substitutions"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.items.empty:
            return self.empty("No line items in this period.")

        cur = d.items.groupby(["product_id", "name", "category"]).agg(
            units=("quantity", "sum"), revenue=("line_amount", "sum"),
            orders=("order_id", "nunique"),
        ).reset_index()
        cur = cur.merge(d.products[["product_id", "price", "cost"]], on="product_id", how="left")
        cur["margin"] = (cur["revenue"] - cur["units"] * cur["cost"].fillna(0)).round(0)
        cur["margin_pct"] = np.where(
            cur["revenue"] > 0, (cur["margin"] / cur["revenue"] * 100).round(1), 0.0)

        prior = (
            d.prior_items.groupby("product_id").agg(prior_units=("quantity", "sum"),
                                                    prior_revenue=("line_amount", "sum")).reset_index()
            if not d.prior_items.empty else pd.DataFrame(columns=["product_id", "prior_units", "prior_revenue"])
        )
        cur = cur.merge(prior, on="product_id", how="left").fillna({"prior_units": 0, "prior_revenue": 0})
        cur["revenue_delta_pct"] = cur.apply(
            lambda r: self.pct_change(r["revenue"], r["prior_revenue"]), axis=1)

        total_rev = float(cur["revenue"].sum()) or 1.0
        cur["revenue_share_pct"] = (cur["revenue"] / total_rev * 100).round(2)

        # The menu-engineering quadrant: popularity against margin.
        pop_median = float(cur["units"].median())
        margin_median = float(cur["margin_pct"].median())

        def quadrant(r) -> str:
            if r["units"] >= pop_median and r["margin_pct"] >= margin_median:
                return "star"            # keep, feature, never discount
            if r["units"] >= pop_median:
                return "workhorse"       # popular, thin — re-engineer cost or price
            if r["margin_pct"] >= margin_median:
                return "puzzle"          # profitable, ignored — promote or reposition
            return "drag"                # neither — candidate for delisting

        cur["quadrant"] = cur.apply(quadrant, axis=1)

        best = cur.nlargest(10, "revenue")
        worst = cur.nsmallest(10, "revenue")
        declining = cur[(cur["prior_revenue"] > 0) & (cur["revenue_delta_pct"] <= -10)] \
            .nsmallest(10, "revenue_delta_pct")
        by_category = cur.groupby("category").agg(
            revenue=("revenue", "sum"), units=("units", "sum"), items=("product_id", "count")
        ).reset_index().sort_values("revenue", ascending=False)

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "active_items": int(len(cur)),
                "top_item": str(best.iloc[0]["name"]) if not best.empty else "—",
                "top_item_share_pct": float(best.iloc[0]["revenue_share_pct"]) if not best.empty else 0.0,
                "drag_items": int((cur["quadrant"] == "drag").sum()),
                "blended_margin_pct": round(float(cur["margin"].sum() / total_rev * 100), 1),
            },
            series=[
                Series(name="Revenue by top item",
                       points=[{"label": r["name"], "value": round(float(r["revenue"]), 0)}
                               for _, r in best.head(8).iterrows()], unit=ctx.currency),
                Series(name="Revenue by category",
                       points=[{"label": r["category"] or "Uncategorised",
                                "value": round(float(r["revenue"]), 0)}
                               for _, r in by_category.head(6).iterrows()], unit=ctx.currency),
            ],
            tables={
                "best_sellers": best[["name", "category", "units", "revenue", "margin_pct",
                                      "revenue_delta_pct", "quadrant"]].round(1).to_dict("records"),
                "worst_sellers": worst[["name", "category", "units", "revenue", "margin_pct",
                                        "quadrant"]].round(1).to_dict("records"),
                "declining": declining[["name", "category", "revenue", "prior_revenue",
                                        "revenue_delta_pct"]].round(1).to_dict("records"),
                "by_category": by_category.round(0).to_dict("records"),
                "quadrants": cur["quadrant"].value_counts().reset_index().rename(
                    columns={"index": "quadrant", "count": "items"}).to_dict("records"),
            },
        )

        if not declining.empty:
            worst_row = declining.iloc[0]
            # Was the whole category down, or just this item? That changes the answer entirely.
            cat_now = float(cur[cur["category"] == worst_row["category"]]["revenue"].sum())
            cat_prior = float(cur[cur["category"] == worst_row["category"]]["prior_revenue"].sum())
            cat_delta = self.pct_change(cat_now, cat_prior)
            item_specific = abs(worst_row["revenue_delta_pct"]) > abs(cat_delta) + 5
            result.findings.append(Finding(
                headline=f"{worst_row['name']} fell {abs(worst_row['revenue_delta_pct']):.1f}% "
                         "against the prior period.",
                reasoning=(
                    f"Its category, {worst_row['category']}, moved {cat_delta:+.1f}% over the same "
                    + ("window, so this is specific to the item rather than a category-wide shift. "
                       "Item-specific decline usually points at price, availability, or quality "
                       "perception."
                       if item_specific else
                       "window, so the item is moving with its category rather than failing on its "
                       "own. A category-wide shift needs a category response, not an item promotion.")
                ),
                actions=[
                    Action(
                        f"Pull the last 30 days of feedback mentioning {worst_row['name']} before "
                        "changing price — check whether this is demand or quality."
                        if item_specific else
                        f"Treat {worst_row['category']} as the unit: review the whole category's "
                        "pricing and placement rather than this one item.",
                        owner="category", effort="low", horizon="this week"),
                    Action(f"If the item is a {worst_row['quadrant']}, "
                           + {"star": "protect it — do not discount a star to fix a volume dip.",
                              "workhorse": "re-engineer its cost before cutting its price.",
                              "puzzle": "give it menu position rather than a discount.",
                              "drag": "put it on the delist review list."}.get(
                               worst_row["quadrant"], "review its position."),
                           owner="category", effort="medium", horizon="this month"),
                ],
                kind="risk", severity="high" if worst_row["revenue_delta_pct"] <= -20 else "medium",
                confidence=0.8, metric_value=round(float(worst_row["revenue"]), 0),
                metric_delta_pct=float(worst_row["revenue_delta_pct"]),
                product_id=str(worst_row["product_id"]),
                evidence={"category_delta_pct": cat_delta, "item_specific": bool(item_specific)},
            ))

        puzzles = cur[cur["quadrant"] == "puzzle"].nlargest(3, "margin_pct")
        if not puzzles.empty:
            p = puzzles.iloc[0]
            result.findings.append(Finding(
                headline=f"{p['name']} carries {p['margin_pct']:.0f}% margin but sits in the "
                         "bottom half on volume.",
                reasoning=(
                    f"It earns {self.money(float(p['margin']), ctx.currency)} on only "
                    f"{int(p['units'])} units. High margin with low volume is a visibility problem, "
                    "not a pricing one — the item is profitable when it does sell."
                ),
                actions=[Action(
                    f"Move {p['name']} into a featured position or bundle it with a star item for "
                    "two weeks, then compare units against this baseline.",
                    owner="category", effort="low", horizon="this month",
                    expected_impact="Margin mix improves without a price change")],
                kind="opportunity", severity="medium", confidence=0.68,
                metric_value=float(p["margin_pct"]), product_id=str(p["product_id"]),
            ))

        drags = int((cur["quadrant"] == "drag").sum())
        if drags >= 3:
            drag_rev = float(cur[cur["quadrant"] == "drag"]["revenue"].sum())
            result.findings.append(Finding(
                headline=f"{drags} items are below median on both volume and margin.",
                reasoning=(
                    f"Together they contribute {drag_rev / total_rev:.1%} of revenue while taking "
                    "up menu space, prep complexity, and inventory. Menu length has an operational "
                    "cost that does not show up in any single item's numbers."
                ),
                actions=[Action(
                    "Run a delist review on these items — check for substitution first, so removing "
                    "them moves demand rather than losing it.",
                    owner="category", effort="medium", horizon="this quarter")],
                kind="opportunity", severity="low", confidence=0.65, metric_value=float(drags),
                evidence={"drag_revenue_share": round(drag_rev / total_rev * 100, 2)},
            ))

        result.narrative = (
            f"{len(cur)} items sold in {ctx.label()}. "
            + (f"{best.iloc[0]['name']} leads at {best.iloc[0]['revenue_share_pct']:.1f}% of revenue. "
               if not best.empty else "")
            + f"{drags} items sit in the drag quadrant."
        )
        return result


class BasketAnalysisModule(IntelligenceModule):
    key = "basket_analysis"
    title = "Basket analysis"
    question = "What are they buying?"
    business_output = "Combo and cross-sell opportunities"
    reads = "Items purchased together"

    min_rows = 30

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.items.empty:
            return self.empty("No line items to co-occur.")

        # One row per (basket, distinct item). Everything below is derived from this
        # frame with vectorised pandas: a groupby-apply with a Python lambda over tens of
        # thousands of baskets dominates the whole dashboard's response time, and the
        # original did two of them — one of which only recomputed what the other had.
        pairs_src = d.items[["order_id", "name"]].dropna().drop_duplicates()
        n_baskets = int(d.items["order_id"].nunique())

        # Baskets containing each item — the denominator for confidence.
        item_counts = pairs_src["name"].value_counts()

        sizes = pairs_src.groupby("order_id")["name"].size()
        multi_ids = sizes.index[sizes >= 2]
        n_multi = int(len(multi_ids))
        if n_multi < 10:
            return self.empty(
                f"Only {n_multi} multi-item baskets in this period — too few for reliable "
                "association rules."
            )

        # Self-join on the basket, keeping each unordered pair once.
        multi_src = pairs_src[pairs_src["order_id"].isin(multi_ids)]
        joined = multi_src.merge(multi_src, on="order_id")
        joined = joined[joined["name_x"] < joined["name_y"]]
        pair_counts = joined.groupby(["name_x", "name_y"]).size()

        rules = []
        for (a, b), co in pair_counts.items():
            if co < 3:
                continue
            support = co / n_baskets
            for x, y in ((a, b), (b, a)):
                conf = co / max(int(item_counts.get(x, 0)), 1)
                base = int(item_counts.get(y, 0)) / n_baskets
                lift = conf / base if base > 0 else 0.0
                rules.append({
                    "antecedent": x, "consequent": y, "co_occurrences": int(co),
                    "support_pct": round(support * 100, 2),
                    "confidence_pct": round(conf * 100, 1),
                    "lift": round(lift, 2),
                })
        rules.sort(key=lambda r: (r["lift"], r["confidence_pct"]), reverse=True)
        strong = [r for r in rules if r["lift"] >= 1.2 and r["confidence_pct"] >= 15][:30]

        # Where the money is: pairs that co-occur often but are not yet bundled.
        avg_basket = float(d.orders["net_amount"].mean()) if not d.orders.empty else 0.0
        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "baskets_analysed": n_baskets,
                "multi_item_baskets": n_multi,
                "multi_item_rate_pct": round(n_multi / max(n_baskets, 1) * 100, 1),
                "strong_rules": len(strong),
                "avg_items_per_basket": round(float(d.items.groupby("order_id")["quantity"].sum().mean()), 2),
            },
            series=[Series(
                name="Strongest pairings by lift",
                points=[{"label": f"{r['antecedent']} → {r['consequent']}", "value": r["lift"]}
                        for r in strong[:8]], unit="lift")],
            tables={
                "rules": strong,
                "top_singles": [{"item": str(k), "orders": int(v),
                                 "penetration_pct": round(int(v) / max(n_baskets, 1) * 100, 1)}
                                for k, v in item_counts.head(15).items()],
            },
        )

        if strong:
            top = strong[0]
            missed = int(item_counts.get(top["antecedent"], 0)) - top["co_occurrences"]
            uplift = missed * 0.25 * (avg_basket * 0.2)
            result.findings.append(Finding(
                headline=f"Customers who order {top['antecedent']} take {top['consequent']} "
                         f"{top['confidence_pct']:.0f}% of the time — {top['lift']}× the base rate.",
                reasoning=(
                    f"The pair appeared together in {top['co_occurrences']} baskets. A lift of "
                    f"{top['lift']} means the pairing is a real behaviour, not an artefact of both "
                    f"items being popular. {missed} baskets contained {top['antecedent']} without "
                    f"{top['consequent']} — that gap is the addressable opportunity."
                ),
                actions=[
                    Action(f"Test a {top['antecedent']} + {top['consequent']} bundle priced below "
                           "the sum of the parts, in stores where attachment is below the network "
                           "average.", owner="category", effort="medium", horizon="this month",
                           expected_impact=f"~{self.money(uplift, ctx.currency)} incremental at a "
                                           "25% conversion on the gap"),
                    Action(f"Prompt {top['consequent']} at the point of order when "
                           f"{top['antecedent']} is in the basket.",
                           owner="operations", effort="low", horizon="this week"),
                ],
                kind="opportunity", severity="medium", confidence=0.78,
                metric_value=float(top["lift"]), estimated_impact=round(uplift, 0),
                evidence={"rule": top, "baskets_without": missed},
            ))

        single_rate = 100 - round(n_multi / max(n_baskets, 1) * 100, 1)
        if single_rate >= 40:
            result.findings.append(Finding(
                headline=f"{single_rate:.0f}% of orders contain only one item.",
                reasoning=(
                    "Single-item baskets are the cheapest basket size to grow, because the customer "
                    "is already transacting — no acquisition cost, no new demand needed. The "
                    "association rules above show which second item each single-item order is most "
                    "likely to accept."
                ),
                actions=[Action(
                    "Put one contextual add-on prompt on the single-item path, driven by the top "
                    "rule for whatever is already in the basket.",
                    owner="operations", effort="medium", horizon="this month",
                    expected_impact="Every point of attachment adds directly to average basket")],
                kind="opportunity", severity="medium", confidence=0.7, metric_value=single_rate,
            ))

        result.narrative = (
            f"{n_multi:,} of {n_baskets:,} baskets held more than one item, producing "
            f"{len(strong)} associations strong enough to act on."
        )
        return result


class PriceSensitivityModule(IntelligenceModule):
    key = "price_sensitivity"
    title = "Price sensitivity"
    question = "Why are they buying?"
    business_output = "Pricing and offer insights"
    reads = "Response to pricing and promotions"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.orders.empty or d.items.empty:
            return self.empty()

        o = d.orders.copy()
        o["discount_pct"] = np.where(
            o["gross_amount"] > 0, o["discount_amount"] / o["gross_amount"] * 100, 0.0)
        o["discounted"] = o["discount_pct"] > 0

        disc, full = o[o["discounted"]], o[~o["discounted"]]
        disc_share = len(disc) / max(len(o), 1)

        # Elasticity per item: realised price against units, across days.
        joined = d.items.merge(o[["order_id", "date"]], on="order_id")
        joined["realised_price"] = np.where(
            joined["quantity"] > 0, joined["line_amount"] / joined["quantity"], joined["unit_price"])
        daily = joined.groupby(["product_id", "name", "date"]).agg(
            units=("quantity", "sum"), price=("realised_price", "mean")).reset_index()

        elasticities = []
        for (pid, name), grp in daily.groupby(["product_id", "name"]):
            grp = grp[(grp["price"] > 0) & (grp["units"] > 0)]
            if len(grp) < 7 or grp["price"].nunique() < 3:
                continue
            lp, lq = np.log(grp["price"]), np.log(grp["units"])
            if lp.std() < 1e-6:
                continue
            slope = float(np.polyfit(lp, lq, 1)[0])
            corr = float(np.corrcoef(lp, lq)[0, 1])
            elasticities.append({
                "product_id": pid, "name": name, "elasticity": round(slope, 2),
                "fit_r": round(corr, 2), "observations": int(len(grp)),
                "avg_price": round(float(grp["price"].mean()), 1),
                # A positive slope means units rose with price, which is almost always
                # a confound (promotion, seasonality) rather than a real Giffen effect.
                # Calling it "inelastic" would invite a price rise on noise.
                "band": ("elastic" if slope <= -1.2 else
                         "unit" if slope <= -0.8 else
                         "inelastic" if -0.8 < slope <= -0.05 else "unclear"),
            })
        elasticities.sort(key=lambda e: e["elasticity"])

        disc_basket = float(disc["net_amount"].mean()) if not disc.empty else 0.0
        full_basket = float(full["net_amount"].mean()) if not full.empty else 0.0
        margin_given = float(disc["discount_amount"].sum())

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "discounted_order_share_pct": round(disc_share * 100, 1),
                "avg_discount_pct": round(float(disc["discount_pct"].mean()) if not disc.empty else 0.0, 1),
                "discount_given": round(margin_given, 0),
                "discounted_basket": round(disc_basket, 0),
                "full_price_basket": round(full_basket, 0),
                "items_modelled": len(elasticities),
            },
            series=[Series(
                name="Price elasticity by item",
                points=[{"label": e["name"], "value": e["elasticity"]} for e in elasticities[:8]],
                unit="elasticity")],
            tables={
                "elasticity": elasticities[:25],
                "discount_bands": (
                    o.assign(band=pd.cut(o["discount_pct"], [-0.1, 0.01, 10, 20, 30, 100],
                                         labels=["none", "1-10%", "10-20%", "20-30%", "30%+"]))
                    .groupby("band", observed=True)
                    .agg(orders=("order_id", "count"), avg_basket=("net_amount", "mean"),
                         revenue=("net_amount", "sum"))
                    .reset_index().round(0).astype({"band": str}).to_dict("records")
                ),
            },
        )

        if elasticities:
            most_elastic = elasticities[0]
            if most_elastic["elasticity"] <= -1.2 and abs(most_elastic["fit_r"]) >= 0.4:
                result.findings.append(Finding(
                    headline=f"{most_elastic['name']} is price-elastic at "
                             f"{most_elastic['elasticity']}.",
                    reasoning=(
                        f"Across {most_elastic['observations']} days, a 1% price rise is associated "
                        f"with a {abs(most_elastic['elasticity']):.1f}% fall in units "
                        f"(fit r = {most_elastic['fit_r']}). An elasticity past −1 means revenue "
                        "falls when price rises — the volume lost outweighs the extra margin per unit."
                    ),
                    actions=[
                        Action(f"Do not take a straight price rise on {most_elastic['name']}. If "
                               "margin is the goal, change the cost side or bundle it instead.",
                               owner="pricing", effort="low", horizon="this week"),
                        Action("Test the price change in a small store group first, and read units "
                               "rather than revenue for the first two weeks.",
                               owner="pricing", effort="medium", horizon="this month"),
                    ],
                    kind="risk", severity="high", confidence=min(0.85, abs(most_elastic["fit_r"])),
                    metric_value=most_elastic["elasticity"],
                    product_id=str(most_elastic["product_id"]),
                    evidence={"top_five": elasticities[:5]},
                ))

            inelastic = [
                e for e in elasticities
                if e["band"] == "inelastic" and abs(e["fit_r"]) >= 0.3
            ]
            if inelastic:
                # The least responsive item that is still genuinely downward-sloping.
                i = max(inelastic, key=lambda e: e["elasticity"])
                result.findings.append(Finding(
                    headline=f"{i['name']} shows little price response at {i['elasticity']}.",
                    reasoning=(
                        "Units barely move with price across the observed range, which means the "
                        "item is bought on preference rather than price. Headroom exists that the "
                        "current price is not capturing."
                    ),
                    actions=[Action(
                        f"Test a modest price increase on {i['name']} in a control group of stores, "
                        "and watch attachment rather than just units — the risk is basket "
                        "composition, not this item.",
                        owner="pricing", effort="medium", horizon="this quarter",
                        expected_impact="Margin gain with limited volume risk")],
                    kind="opportunity", severity="medium", confidence=0.6,
                    metric_value=i["elasticity"], product_id=str(i["product_id"]),
                ))

        if disc_share >= 0.3 and disc_basket <= full_basket * 1.05:
            result.findings.append(Finding(
                headline=f"{disc_share:.0%} of orders carry a discount, but discounted baskets are "
                         "no larger than full-price ones.",
                reasoning=(
                    f"Discounted orders average {self.money(disc_basket, ctx.currency)} against "
                    f"{self.money(full_basket, ctx.currency)} at full price, and "
                    f"{self.money(margin_given, ctx.currency)} of margin was given away in the "
                    "period. A discount that does not enlarge the basket is subsidising demand "
                    "that was already there."
                ),
                actions=[
                    Action("Switch flat discounts to threshold offers — value unlocked only above a "
                           "basket size — so the discount buys incremental spend.",
                           owner="pricing", effort="medium", horizon="this month",
                           expected_impact=f"Recovers part of {self.money(margin_given, ctx.currency)}"),
                    Action("Hold a no-discount control group to measure what the discount is "
                           "actually buying.", owner="marketing", effort="low", horizon="this week"),
                ],
                kind="risk", severity="high", confidence=0.76,
                metric_value=round(disc_share * 100, 1), estimated_impact=round(margin_given * 0.3, 0),
            ))

        result.narrative = (
            f"{disc_share:.0%} of orders were discounted, costing "
            f"{self.money(margin_given, ctx.currency)}. "
            f"{len(elasticities)} items had enough price variation to model."
        )
        return result


class TrendDetectionModule(IntelligenceModule):
    key = "trend_detection"
    title = "Trend detection"
    question = "What should we offer them next?"
    business_output = "New product opportunities"
    reads = "Emerging food preferences and customer conversations"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        rising, falling = [], []

        # Signal 1: items accelerating in the second half of the period against the first.
        if not d.items.empty and not d.orders.empty:
            j = d.items.merge(d.orders[["order_id", "placed_at"]], on="order_id")
            midpoint = ctx.period_start + (ctx.period_end - ctx.period_start) / 2
            first = j[j["placed_at"] < midpoint].groupby("name")["quantity"].sum()
            second = j[j["placed_at"] >= midpoint].groupby("name")["quantity"].sum()
            for name in set(first.index) | set(second.index):
                a, b = float(first.get(name, 0)), float(second.get(name, 0))
                if a + b < 10:
                    continue
                delta = self.pct_change(b, a)
                row = {"item": name, "first_half_units": a, "second_half_units": b,
                       "momentum_pct": delta, "signal": "sales"}
                if delta >= 20:
                    rising.append(row)
                elif delta <= -20:
                    falling.append(row)

        # Signal 2: language rising in customer conversations before it shows up in sales.
        theme_rise = []
        rising_complaints = []
        if not d.feedback.empty:
            cur_themes = Counter()
            theme_sentiment: dict[str, list[float]] = {}
            for _, row in d.feedback.iterrows():
                for x in str(row["themes"]).split(","):
                    x = x.strip()
                    if x:
                        cur_themes[x] += 1
                        theme_sentiment.setdefault(x, []).append(float(row["sentiment_score"]))
            prior_themes = Counter()
            if not d.prior_feedback.empty:
                for t in d.prior_feedback["themes"].fillna(""):
                    prior_themes.update([x.strip() for x in str(t).split(",") if x.strip()])
            n_cur = max(len(d.feedback), 1)
            n_prior = max(len(d.prior_feedback), 1)
            for theme, count in cur_themes.most_common(30):
                cur_rate = count / n_cur
                prior_rate = prior_themes.get(theme, 0) / n_prior
                delta = self.pct_change(cur_rate, prior_rate)
                if count < 4 or delta < 25:
                    continue
                scores = theme_sentiment.get(theme, [0.5])
                avg_sentiment = sum(scores) / len(scores)
                row = {
                    "theme": theme, "mentions": count,
                    "share_pct": round(cur_rate * 100, 1), "momentum_pct": delta,
                    "avg_sentiment": round(avg_sentiment, 3), "signal": "conversation",
                }
                # A complaint climbing the charts is a rising concern, which voice of
                # customer owns. Reporting it here as an "emerging trend" would put the
                # same theme under two different headings and mean neither.
                if avg_sentiment < 0.4:
                    rising_complaints.append(row)
                else:
                    theme_rise.append(row)
        # Signal 3: language rising in the text itself.
        # Themes are a fixed vocabulary, so a preference the business has no word for yet
        # — the exact case worth catching — is invisible to them. Comparing the actual
        # phrases customers use across the two halves of the window catches it.
        term_rise = self._rising_terms(ctx, d)

        theme_rise.sort(key=lambda t: t["momentum_pct"], reverse=True)
        rising.sort(key=lambda r: r["momentum_pct"], reverse=True)
        falling.sort(key=lambda r: r["momentum_pct"])

        if not rising and not theme_rise and not falling and not rising_complaints \
                and not term_rise:
            return self.empty("No item or conversation moved enough in this period to call a trend.")

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "rising_items": len(rising),
                "falling_items": len(falling),
                "rising_conversations": len(theme_rise) + len(term_rise),
                # The headline trend is a preference, never a complaint: a rising
                # phrase first, then a rising item, then a positive theme.
                "top_trend": (term_rise[0]["term"] if term_rise
                              else rising[0]["item"] if rising
                              else theme_rise[0]["theme"] if theme_rise else "—"),
            },
            series=[Series(
                name="Momentum, second half against first",
                points=[{"label": r["item"], "value": round(r["momentum_pct"], 1)}
                        for r in (rising[:5] + falling[:3])], unit="%")],
            tables={"rising": rising[:15], "falling": falling[:15],
                    "conversation_trends": theme_rise[:15],
                    "rising_language": term_rise[:15],
                    "rising_complaints": rising_complaints[:10]},
        )

        if term_rise:
            t = term_rise[0]
            result.findings.append(Finding(
                headline=f"'{t['term']}' is rising in what customers are writing, up "
                         f"{t['momentum_pct']:.0f}% on the prior period.",
                reasoning=(
                    f"{t['mentions']} mentions this period against {t['prior_mentions']} in the "
                    f"one before, at an average sentiment of {t['avg_sentiment']:.2f}. "
                    + ("The catalogue already has something matching this language, so the gap "
                       "is visibility rather than range — customers are asking for a thing you "
                       "sell."
                       if t["in_catalogue"] else
                       "Nothing in the catalogue matches this phrase. Conversation moves before "
                       "sales do, which makes this a range decision rather than a promotion one.")
                ),
                actions=[Action(
                    f"Feature the matching items using the customers' own phrase — '{t['term']}' "
                    "— in the copy, and read the response before committing to anything new."
                    if t["in_catalogue"] else
                    f"Brief the product team on a limited-time item around '{t['term']}' and test "
                    "it in the stores where the mentions concentrate.",
                    owner="category", effort="medium" if t["in_catalogue"] else "high",
                    horizon="this month" if t["in_catalogue"] else "this quarter")],
                kind="trend", severity="medium", confidence=0.6,
                metric_value=float(t["mentions"]), metric_delta_pct=t["momentum_pct"],
                evidence={"in_catalogue": t["in_catalogue"], "top_terms": term_rise[:5]},
            ))

        if theme_rise:
            t = theme_rise[0]
            in_menu = (not d.products.empty and
                       d.products["name"].str.lower().str.contains(t["theme"].lower(), na=False).any())
            result.findings.append(Finding(
                headline=f"'{t['theme']}' is rising in customer conversation, up "
                         f"{t['momentum_pct']:.0f}% on the prior period.",
                reasoning=(
                    f"{t['mentions']} mentions, {t['share_pct']}% of all feedback this period. "
                    + ("The catalogue already has something matching this language, so the gap is "
                       "visibility rather than range."
                       if in_menu else
                       "Nothing in the current catalogue matches this language. Conversation "
                       "usually moves before sales do, which is what makes this a range decision "
                       "rather than a promotion decision.")
                ),
                actions=[Action(
                    f"Feature the matching items and use the customers' own word — '{t['theme']}' — "
                    "in the copy." if in_menu else
                    f"Brief the product team on a limited-time item around '{t['theme']}' and test "
                    "it in the stores where the mentions concentrate.",
                    owner="category", effort="medium" if in_menu else "high",
                    horizon="this month" if in_menu else "this quarter")],
                kind="trend", severity="medium", confidence=0.62,
                metric_value=float(t["mentions"]), metric_delta_pct=t["momentum_pct"],
                evidence={"in_catalogue": bool(in_menu), "top_themes": theme_rise[:5]},
            ))

        if rising:
            r = rising[0]
            result.findings.append(Finding(
                headline=f"{r['item']} accelerated {r['momentum_pct']:.0f}% in the second half of "
                         "the period.",
                reasoning=(
                    f"Units went from {r['first_half_units']:.0f} to {r['second_half_units']:.0f} "
                    "across the two halves. Momentum inside a period is an earlier signal than a "
                    "period-over-period comparison, which averages the acceleration away."
                ),
                actions=[Action(
                    f"Check stock and prep capacity for {r['item']} before promoting it — "
                    "accelerating demand fails loudest when the item runs out.",
                    owner="operations", effort="low", horizon="this week")],
                kind="trend", severity="low", confidence=0.6,
                metric_value=r["second_half_units"], metric_delta_pct=r["momentum_pct"],
            ))

        result.narrative = (
            f"{len(rising)} items accelerating, {len(falling)} decelerating, "
            f"{len(term_rise)} phrases rising in customer language, and "
            f"{len(theme_rise)} themes rising in conversation."
        )
        return result

    def _rising_terms(self, ctx: AnalysisContext, d) -> list[dict]:
        """Phrases gaining ground in customer text, current period against the prior one."""
        if d.feedback.empty:
            return []

        def phrases(texts) -> Counter:
            bag: Counter = Counter()
            for raw in texts:
                # Sentence boundaries matter: a bigram must not span a full stop.
                for clause in re.split(r"[.!?,;]", str(raw).lower()):
                    words = [w.strip("'\"()") for w in clause.split()]
                    keep = [
                        w if len(w) > 3 and w not in _TERM_STOPWORDS else None
                        for w in words
                    ]
                    bag.update(w for w in keep if w)
                    # Bigrams catch "spicy chicken", which neither word carries alone.
                    # Both halves must be adjacent in the source — building them from the
                    # filtered list instead would invent phrases like "fast arrived" out
                    # of words that had three stopwords between them.
                    for a, b in zip(keep, keep[1:], strict=False):
                        if a and b:
                            bag[f"{a} {b}"] += 1
            return bag

        cur = phrases(d.feedback["body"])
        prior = phrases(d.prior_feedback["body"]) if not d.prior_feedback.empty else Counter()
        n_cur = max(len(d.feedback), 1)
        n_prior = max(len(d.prior_feedback), 1)

        # Average sentiment of the rows a phrase appears in, so a rising complaint is not
        # reported as a rising preference.
        sentiment_of: dict[str, list[float]] = {}
        for _, row in d.feedback.iterrows():
            body = str(row["body"]).lower()
            score = float(row["sentiment_score"])
            for term in cur:
                if term in body:
                    sentiment_of.setdefault(term, []).append(score)

        catalogue = (
            set(d.products["name"].dropna().str.lower()) if not d.products.empty else set()
        )

        out = []
        for term, count in cur.most_common(400):
            if count < 4:
                continue
            cur_rate = count / n_cur
            prior_rate = prior.get(term, 0) / n_prior
            delta = self.pct_change(cur_rate, prior_rate)
            if delta < 30:
                continue
            scores = sentiment_of.get(term, [0.5])
            avg = sum(scores) / len(scores)
            if avg <= 0.52:
                continue   # neutral or negative: a complaint or a remark, not a preference
            out.append({
                "term": term,
                "mentions": count,
                "prior_mentions": prior.get(term, 0),
                "share_pct": round(cur_rate * 100, 1),
                "momentum_pct": delta,
                "avg_sentiment": round(avg, 3),
                "in_catalogue": any(term in name for name in catalogue),
                "signal": "language",
            })

        # Prefer multi-word phrases: "spicy chicken" is a product idea, "spicy" is a note.
        out.sort(key=lambda t: (" " in t["term"], t["mentions"], t["momentum_pct"]), reverse=True)
        return out


# Words that carry no product signal. Deliberately includes "food", "order" and "time":
# they appear in almost every piece of QSR feedback, so they always look like a trend
# and never are one.
_TERM_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "they", "there", "their", "have", "has",
    "was", "were", "been", "from", "very", "just", "really", "here", "about", "would",
    "could", "your", "them", "then", "than", "into", "over", "when", "what", "which",
    "always", "never", "also", "more", "most", "some", "such", "only", "much", "many",
    "please", "will", "want", "need", "like", "make", "made", "back", "even", "still",
    "order", "ordered", "ordering", "food", "time", "good", "nice", "okay", "well",
    "today", "again", "everything", "something", "anything", "store", "staff",
}
