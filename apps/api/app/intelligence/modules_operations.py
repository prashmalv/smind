"""Modules that read execution rather than the customer.

campaign_intelligence · store_intelligence

Store intelligence is where the camera layer earns its place: footfall from cameras and
orders from the POS together give conversion, which neither source has on its own.
"""

from __future__ import annotations

import json

import pandas as pd

from app.intelligence.base import (
    Action,
    AnalysisContext,
    Finding,
    IntelligenceModule,
    ModuleResult,
    Series,
)


class CampaignIntelligenceModule(IntelligenceModule):
    key = "campaign_intelligence"
    title = "Campaign intelligence"
    question = "What should we offer them next?"
    business_output = "Campaign effectiveness"
    reads = "Offers versus customer response"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.campaigns.empty:
            return self.empty("No campaigns recorded. Connect your CRM or campaign tool.")

        c = d.campaigns.copy()
        c["redemption_rate_pct"] = (c["redemptions"] / c["reach"].clip(lower=1) * 100).round(2)
        c["roi"] = (c["attributed_revenue"] / c["budget"].clip(lower=1)).round(2)
        c["cost_per_redemption"] = (c["budget"] / c["redemptions"].clip(lower=1)).round(1)
        c = c.sort_values("roi", ascending=False)

        total_spend = float(c["budget"].sum())
        total_return = float(c["attributed_revenue"].sum())
        blended_roi = round(total_return / total_spend, 2) if total_spend else 0.0

        by_objective = c.groupby("objective").agg(
            campaigns=("campaign_id", "count"), budget=("budget", "sum"),
            revenue=("attributed_revenue", "sum"), avg_redemption=("redemption_rate_pct", "mean"),
        ).reset_index()
        by_objective["roi"] = (by_objective["revenue"] / by_objective["budget"].clip(lower=1)).round(2)
        by_objective = by_objective.sort_values("roi", ascending=False)

        by_channel = c.groupby("channel").agg(
            campaigns=("campaign_id", "count"), avg_redemption=("redemption_rate_pct", "mean"),
            revenue=("attributed_revenue", "sum"), budget=("budget", "sum"),
        ).reset_index()
        by_channel["roi"] = (by_channel["revenue"] / by_channel["budget"].clip(lower=1)).round(2)

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "campaigns": int(len(c)),
                "total_spend": round(total_spend, 0),
                "attributed_revenue": round(total_return, 0),
                "blended_roi": blended_roi,
                "avg_redemption_pct": round(float(c["redemption_rate_pct"].mean()), 2),
                "loss_making": int((c["roi"] < 1).sum()),
            },
            series=[
                Series(name="Return on spend by campaign",
                       points=[{"label": r["name"], "value": float(r["roi"])}
                               for _, r in c.head(8).iterrows()], unit="×"),
                Series(name="Redemption rate by channel",
                       points=[{"label": r["channel"], "value": round(float(r["avg_redemption"]), 1)}
                               for _, r in by_channel.iterrows()], unit="%"),
            ],
            tables={
                "campaigns": c[["name", "objective", "channel", "target_segment", "reach",
                                "redemptions", "redemption_rate_pct", "budget",
                                "attributed_revenue", "roi", "cost_per_redemption"]]
                             .round(2).to_dict("records"),
                "by_objective": by_objective.round(2).to_dict("records"),
                "by_channel": by_channel.round(2).to_dict("records"),
            },
        )

        losers = c[c["roi"] < 1]
        if not losers.empty:
            wasted = float((losers["budget"] - losers["attributed_revenue"]).sum())
            worst = losers.nsmallest(1, "roi").iloc[0]
            result.findings.append(Finding(
                headline=f"{len(losers)} campaigns returned less than they cost, "
                         f"{self.money(wasted, ctx.currency)} net.",
                reasoning=(
                    f"The weakest is '{worst['name']}' at {worst['roi']}× on a "
                    f"{self.money(float(worst['budget']), ctx.currency)} budget, with a "
                    f"{worst['redemption_rate_pct']}% redemption rate against a portfolio average "
                    f"of {float(c['redemption_rate_pct'].mean()):.1f}%. Low redemption on adequate "
                    "reach points at the offer or the target, not the channel."
                ),
                actions=[
                    Action(f"Stop '{worst['name']}' in its current form and re-target it at the "
                           f"segment with the highest response to {worst['objective']} offers.",
                           owner="marketing", effort="low", horizon="this week",
                           expected_impact=f"Recovers {self.money(wasted, ctx.currency)} of spend"),
                    Action(f"Shift that budget to {by_objective.iloc[0]['objective']} campaigns, "
                           f"which return {by_objective.iloc[0]['roi']}× across "
                           f"{int(by_objective.iloc[0]['campaigns'])} runs.",
                           owner="marketing", effort="low", horizon="this month"),
                ],
                kind="risk", severity="high", confidence=0.82,
                metric_value=float(len(losers)), estimated_impact=round(wasted, 0),
                evidence={"worst": worst[["name", "roi", "budget"]].to_dict()},
            ))

        if len(by_objective) >= 2:
            best, worst_obj = by_objective.iloc[0], by_objective.iloc[-1]
            if best["roi"] >= worst_obj["roi"] * 1.5 and worst_obj["budget"] > 0:
                shiftable = float(worst_obj["budget"]) * 0.4
                result.findings.append(Finding(
                    headline=f"{best['objective'].title()} campaigns return {best['roi']}× against "
                             f"{worst_obj['roi']}× for {worst_obj['objective']}.",
                    reasoning=(
                        f"Across {int(best['campaigns'])} {best['objective']} runs and "
                        f"{int(worst_obj['campaigns'])} {worst_obj['objective']} runs, the gap is "
                        "wide enough to act on. Campaign budget is usually allocated by habit "
                        "rather than by measured return."
                    ),
                    actions=[Action(
                        f"Move {self.money(shiftable, ctx.currency)} — 40% of {worst_obj['objective']} "
                        f"budget — into {best['objective']} for the next cycle and compare.",
                        owner="marketing", effort="low", horizon="this quarter",
                        expected_impact=f"~{self.money(shiftable * (float(best['roi']) - float(worst_obj['roi'])), ctx.currency)} "
                                        "at the observed return gap")],
                    kind="opportunity", severity="medium", confidence=0.7,
                    metric_value=float(best["roi"]), estimated_impact=round(shiftable, 0),
                ))

        result.narrative = (
            f"{len(c)} campaigns, {self.money(total_spend, ctx.currency)} spent, "
            f"{self.money(total_return, ctx.currency)} attributed — a blended {blended_roi}× return."
        )
        return result


class StoreIntelligenceModule(IntelligenceModule):
    key = "store_intelligence"
    title = "Store intelligence"
    question = "Who is buying?"
    business_output = "Location-level insights"
    reads = "Store-wise demand, footfall, conversion"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.orders.empty:
            return self.empty()

        cur = d.orders.groupby("store_id").agg(
            orders=("order_id", "count"), revenue=("net_amount", "sum"),
            avg_basket=("net_amount", "mean"),
            customers=("customer_id", "nunique"),
            avg_fulfilment=("fulfilment_minutes", "mean"),
        ).reset_index()

        prior = (d.prior_orders.groupby("store_id").agg(
            prior_revenue=("net_amount", "sum"), prior_orders=("order_id", "count")).reset_index()
            if not d.prior_orders.empty else pd.DataFrame(columns=["store_id", "prior_revenue", "prior_orders"]))
        cur = cur.merge(prior, on="store_id", how="left").fillna({"prior_revenue": 0, "prior_orders": 0})
        cur["revenue_delta_pct"] = cur.apply(
            lambda r: self.pct_change(r["revenue"], r["prior_revenue"]), axis=1)

        # ── the camera join: footfall from vision, orders from POS → conversion ──
        has_vision = not d.camera_events.empty
        if has_vision:
            entry = d.camera_events[d.camera_events["zone_type"].isin(["entrance", "drive-thru"])]
            foot = entry.groupby("store_id").agg(
                footfall=("footfall_in", "sum"), unique_visitors=("unique_visitors", "sum"),
            ).reset_index()
            queue = d.camera_events[d.camera_events["zone_type"] == "queue"].groupby("store_id").agg(
                avg_queue=("avg_queue_length", "mean"), max_queue=("max_queue_length", "max"),
                avg_wait_s=("avg_wait_seconds", "mean"), abandonments=("abandonment_count", "sum"),
            ).reset_index()
            dwell = d.camera_events[d.camera_events["zone_type"].isin(["aisle", "display", "counter"])] \
                .groupby("store_id").agg(avg_dwell_s=("avg_dwell_seconds", "mean")).reset_index()
            for frame in (foot, queue, dwell):
                if not frame.empty:
                    cur = cur.merge(frame, on="store_id", how="left")
            if "footfall" in cur:
                cur["conversion_pct"] = (
                    cur["orders"] / cur["footfall"].replace(0, pd.NA) * 100).round(1)

        cur["store_name"] = cur["store_id"].map(d.store_name)
        if not d.stores.empty:
            cur = cur.merge(d.stores[["store_id", "city", "region", "format"]], on="store_id", how="left")
        cur = cur.sort_values("revenue", ascending=False)

        metrics = {
            "stores": int(len(cur)),
            "network_revenue": round(float(cur["revenue"].sum()), 0),
            "best_store": str(cur.iloc[0]["store_name"]) if not cur.empty else "—",
            "stores_declining": int((cur["revenue_delta_pct"] < -5).sum()),
        }
        if has_vision and "conversion_pct" in cur:
            conv = cur["conversion_pct"].dropna()
            metrics["network_footfall"] = int(cur.get("footfall", pd.Series([0])).fillna(0).sum())
            metrics["avg_conversion_pct"] = round(float(conv.mean()), 1) if not conv.empty else 0.0

        display_cols = [c for c in [
            "store_name", "city", "format", "orders", "revenue", "avg_basket",
            "revenue_delta_pct", "footfall", "conversion_pct", "avg_queue", "avg_wait_s",
            "abandonments", "avg_dwell_s", "avg_fulfilment",
        ] if c in cur.columns]

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics=metrics,
            series=[Series(
                name="Revenue by store",
                points=[{"label": r["store_name"], "value": round(float(r["revenue"]), 0)}
                        for _, r in cur.head(10).iterrows()], unit=ctx.currency)],
            tables={
                "stores": cur[display_cols].round(1).to_dict("records"),
                "declining": cur[cur["revenue_delta_pct"] < -5][display_cols].round(1).to_dict("records"),
            },
            coverage_note=("Camera coverage active — conversion is measured, not estimated."
                           if has_vision else
                           "No camera data in this period, so conversion cannot be computed. "
                           "Connect cameras in Settings → Cameras."),
        )
        if has_vision and "conversion_pct" in cur:
            result.series.append(Series(
                name="Conversion by store",
                points=[{"label": r["store_name"], "value": float(r["conversion_pct"])}
                        for _, r in cur.dropna(subset=["conversion_pct"]).head(10).iterrows()],
                unit="%"))

        # ── findings ────────────────────────────────────────────────────────
        declining = cur[cur["revenue_delta_pct"] <= -7]
        if not declining.empty:
            network_delta = self.pct_change(
                float(cur["revenue"].sum()), float(cur["prior_revenue"].sum()))
            worst = declining.nsmallest(1, "revenue_delta_pct").iloc[0]
            concentrated = len(declining) <= max(2, len(cur) * 0.3)
            result.findings.append(Finding(
                headline=f"{len(declining)} stores are down more than 7%, led by "
                         f"{worst['store_name']} at {worst['revenue_delta_pct']:.1f}%.",
                reasoning=(
                    f"The network as a whole moved {network_delta:+.1f}%. "
                    + ("The decline is concentrated in a small group rather than spread across the "
                       "estate, which points at local execution — staffing, a competitor opening, "
                       "or a site-specific operational change — rather than brand or pricing."
                       if concentrated else
                       "The decline is spread across much of the estate, which points at a "
                       "brand-level cause: pricing, menu, or a category-wide shift. A store visit "
                       "will not fix a network problem.")
                ),
                actions=[
                    Action(f"Visit {worst['store_name']} and pull its feedback verbatims for the "
                           "period." if concentrated else
                           "Review network pricing and menu changes made in the last 60 days "
                           "before assigning this to store teams.",
                           owner="operations" if concentrated else "category",
                           effort="medium", horizon="this week"),
                    Action("Compare the declining stores' conversion against the network — if "
                           "footfall held and conversion fell, the problem is inside the store."
                           if has_vision else
                           "Enable camera coverage at these stores so footfall can be separated "
                           "from conversion.",
                           owner="operations", effort="low" if has_vision else "high",
                           horizon="this week"),
                ],
                kind="risk", severity="high", confidence=0.8,
                metric_value=round(float(worst["revenue"]), 0),
                metric_delta_pct=float(worst["revenue_delta_pct"]),
                store_id=str(worst["store_id"]),
                evidence={"network_delta_pct": network_delta, "concentrated": bool(concentrated),
                          "stores": declining[["store_name", "revenue_delta_pct"]].to_dict("records")},
            ))

        if has_vision and "conversion_pct" in cur:
            conv = cur.dropna(subset=["conversion_pct"])
            if len(conv) >= 3:
                net_conv = float(conv["conversion_pct"].mean())
                laggards = conv[conv["conversion_pct"] < net_conv * 0.75]
                if not laggards.empty:
                    lag = laggards.nsmallest(1, "conversion_pct").iloc[0]
                    lost = float(lag["footfall"]) * (net_conv - float(lag["conversion_pct"])) / 100
                    upside = lost * float(lag["avg_basket"])
                    queue_note = ""
                    if "avg_wait_s" in lag and pd.notna(lag.get("avg_wait_s")):
                        net_wait = float(conv["avg_wait_s"].mean()) if "avg_wait_s" in conv else 0
                        if float(lag["avg_wait_s"]) > net_wait * 1.2:
                            queue_note = (
                                f" Average wait at this store is {float(lag['avg_wait_s']):.0f} "
                                f"seconds against a network {net_wait:.0f} — the queue is the most "
                                "likely cause."
                            )
                    result.findings.append(Finding(
                        headline=f"{lag['store_name']} converts {lag['conversion_pct']:.1f}% of "
                                 f"footfall against a network {net_conv:.1f}%.",
                        reasoning=(
                            f"Cameras counted {int(lag['footfall']):,} visits at this store and the "
                            f"POS recorded {int(lag['orders']):,} orders. People are walking in and "
                            f"leaving without buying.{queue_note} This is the one number neither "
                            "the POS nor the camera can produce alone."
                        ),
                        actions=[
                            Action("Re-staff the counter across the store's two busiest hours and "
                                   "re-read conversion after a week.",
                                   owner="operations", effort="medium", horizon="this week",
                                   expected_impact=f"~{self.money(upside, ctx.currency)} if "
                                                   "conversion reaches the network average"),
                            Action("Check whether the queue-length alert threshold for this store "
                                   "is set to its actual capacity.",
                                   owner="operations", effort="low", horizon="this week"),
                        ],
                        kind="opportunity", severity="high", confidence=0.72,
                        metric_value=float(lag["conversion_pct"]),
                        estimated_impact=round(upside, 0), store_id=str(lag["store_id"]),
                        evidence={"network_conversion_pct": round(net_conv, 1),
                                  "footfall": int(lag["footfall"])},
                    ))

        if len(cur) >= 4:
            top, bottom = cur.iloc[0], cur.iloc[-1]
            gap = self.pct_change(float(top["avg_basket"]), float(bottom["avg_basket"]))
            if gap >= 25:
                result.findings.append(Finding(
                    headline=f"Average basket ranges {gap:.0f}% across the estate, from "
                             f"{top['store_name']} to {bottom['store_name']}.",
                    reasoning=(
                        f"{self.money(float(top['avg_basket']), ctx.currency)} against "
                        f"{self.money(float(bottom['avg_basket']), ctx.currency)} on the same "
                        "catalogue and the same pricing. A spread this wide on identical inputs is "
                        "usually attachment behaviour at the counter rather than customer mix."
                    ),
                    actions=[Action(
                        f"Observe the order-taking script at {top['store_name']} and roll what it "
                        f"does differently into {bottom['store_name']} before changing anything "
                        "structural.", owner="operations", effort="medium", horizon="this month")],
                    kind="opportunity", severity="medium", confidence=0.65,
                    metric_value=round(float(top["avg_basket"]), 0),
                ))

        result.narrative = (
            f"{len(cur)} stores generated {self.money(float(cur['revenue'].sum()), ctx.currency)} "
            f"in {ctx.label()}. "
            + (f"Network conversion is {metrics.get('avg_conversion_pct', 0)}%."
               if has_vision else "Camera coverage is off, so conversion is not available.")
        )
        return result


class StoreVisionModule(IntelligenceModule):
    """Fourteenth module — not in the original thirteen. It exists because the platform now
    has cameras, and footfall, queue and dwell deserve their own reasoning rather than
    being a footnote inside store intelligence."""

    key = "store_vision"
    title = "In-store vision"
    question = "What is stopping them?"
    business_output = "Footfall, queue and dwell insights"
    reads = "Anonymous camera events: entries, queue length, dwell time, zone occupancy"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.camera_events.empty:
            return self.empty(
                "No camera events in this period. Add a camera in Settings → Cameras, or run the "
                "edge agent in simulated mode to generate a feed."
            )

        ev = d.camera_events
        by_hour = ev.groupby("hour").agg(
            footfall=("footfall_in", "sum"), avg_queue=("avg_queue_length", "mean"),
            avg_wait=("avg_wait_seconds", "mean"), abandonments=("abandonment_count", "sum"),
        ).reset_index().sort_values("hour")

        by_zone = ev.groupby("zone_type").agg(
            events=("camera_id", "count"), footfall=("footfall_in", "sum"),
            avg_dwell=("avg_dwell_seconds", "mean"), interactions=("interaction_count", "sum"),
        ).reset_index()

        by_store = ev.groupby("store_id").agg(
            footfall=("footfall_in", "sum"), avg_queue=("avg_queue_length", "mean"),
            max_queue=("max_queue_length", "max"), abandonments=("abandonment_count", "sum"),
            avg_wait=("avg_wait_seconds", "mean"),
        ).reset_index()
        by_store["store_name"] = by_store["store_id"].map(d.store_name)

        # Anonymous demographic bands, aggregated. No identity is ever stored.
        demo = {}
        for blob in ev["demographics"].dropna():
            try:
                for k, v in json.loads(blob).items():
                    demo[k] = demo.get(k, 0) + int(v)
            except (ValueError, TypeError):
                continue

        total_foot = int(ev["footfall_in"].sum())
        total_aband = int(ev["abandonment_count"].sum())

        # Cross-reference against orders to place the queue against demand.
        peak_hour = int(by_hour.nlargest(1, "footfall").iloc[0]["hour"]) if not by_hour.empty else None
        worst_wait = by_hour.nlargest(1, "avg_wait").iloc[0] if not by_hour.empty else None

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "footfall": total_foot,
                "cameras_reporting": int(ev["camera_id"].nunique()),
                "stores_covered": int(ev["store_id"].nunique()),
                "avg_wait_seconds": round(float(ev["avg_wait_seconds"].mean()), 1),
                "abandonments": total_aband,
                "abandonment_rate_pct": round(total_aband / max(total_foot, 1) * 100, 2),
                "avg_dwell_seconds": round(float(ev["avg_dwell_seconds"].mean()), 1),
            },
            series=[
                Series(name="Footfall by hour",
                       points=[{"label": f"{int(r['hour']):02d}:00", "value": int(r["footfall"])}
                               for _, r in by_hour.iterrows()], unit="visitors"),
                Series(name="Average wait by hour",
                       points=[{"label": f"{int(r['hour']):02d}:00",
                                "value": round(float(r["avg_wait"]), 0)}
                               for _, r in by_hour.iterrows()], unit="seconds"),
            ],
            tables={
                "by_zone": by_zone.round(1).to_dict("records"),
                "by_store": by_store.drop(columns=["store_id"]).round(1).to_dict("records"),
                "by_hour": by_hour.round(1).to_dict("records"),
                "demographics": [{"band": k, "observations": v} for k, v in sorted(demo.items())],
            },
            coverage_note="Events are anonymous aggregates. No face template, identity, or "
                          "biometric join to the customer record is stored.",
        )

        if worst_wait is not None and float(worst_wait["avg_wait"]) > 120:
            lost_orders = float(worst_wait["abandonments"])
            avg_basket = float(d.orders["net_amount"].mean()) if not d.orders.empty else 0.0
            result.findings.append(Finding(
                headline=f"Queue wait peaks at {float(worst_wait['avg_wait']):.0f} seconds around "
                         f"{int(worst_wait['hour']):02d}:00.",
                reasoning=(
                    f"{int(worst_wait['abandonments'])} customers left the queue during that window "
                    f"across the period, against {int(worst_wait['footfall'])} entries. "
                    + (f"Footfall peaks at {peak_hour:02d}:00, "
                       + ("which is the same hour — the queue is a capacity problem, not a process "
                          "one." if peak_hour == int(worst_wait["hour"]) else
                          "a different hour — so this is a staffing-schedule mismatch rather than "
                          "raw volume.")
                       if peak_hour is not None else "")
                ),
                actions=[
                    Action(f"Move one staff shift to cover {int(worst_wait['hour']):02d}:00–"
                           f"{int(worst_wait['hour']) + 2:02d}:00 and re-read abandonment after a week.",
                           owner="operations", effort="low", horizon="this week",
                           expected_impact=f"~{self.money(lost_orders * avg_basket, ctx.currency)} "
                                           "of abandoned demand"),
                    Action("Set a live queue alert at this store so the breach is caught in the "
                           "moment rather than in the weekly report.",
                           owner="operations", effort="low", horizon="this week"),
                ],
                kind="risk", severity="high", confidence=0.78,
                metric_value=round(float(worst_wait["avg_wait"]), 0),
                estimated_impact=round(lost_orders * avg_basket, 0),
                evidence={"peak_footfall_hour": peak_hour},
            ))

        if not by_zone.empty and "display" in set(by_zone["zone_type"]):
            disp = by_zone[by_zone["zone_type"] == "display"].iloc[0]
            if float(disp["avg_dwell"]) > 0:
                conv_proxy = float(disp["interactions"]) / max(float(disp["footfall"]), 1)
                if conv_proxy < 0.25:
                    result.findings.append(Finding(
                        headline=f"Display zones see {float(disp['avg_dwell']):.0f} seconds of dwell "
                                 f"but only {conv_proxy:.0%} interaction.",
                        reasoning=(
                            "Customers stop in front of the display and then move on without "
                            "picking anything up. Dwell without interaction usually means the "
                            "display is being read rather than shopped — the message is landing, "
                            "the offer is not."
                        ),
                        actions=[Action(
                            "Change one display's offer rather than its layout, and compare "
                            "interaction rate against the unchanged displays.",
                            owner="category", effort="low", horizon="this month")],
                        kind="opportunity", severity="medium", confidence=0.58,
                        metric_value=round(conv_proxy * 100, 1),
                    ))

        result.narrative = (
            f"{total_foot:,} visits observed across {int(ev['store_id'].nunique())} stores and "
            f"{int(ev['camera_id'].nunique())} cameras, with an average wait of "
            f"{float(ev['avg_wait_seconds'].mean()):.0f} seconds."
        )
        return result
