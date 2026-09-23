"""Modules that answer *why are they buying* and *what is stopping them*.

sentiment_intelligence · voice_of_customer · competitor_intelligence

These read unstructured text. Enrichment (sentiment, themes) happens at ingest — see
app/services/enrichment.py — so these modules read the enriched columns rather than
calling a language model per request.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from app.intelligence.base import (
    Action,
    AnalysisContext,
    Finding,
    IntelligenceModule,
    ModuleResult,
    Series,
)


class SentimentIntelligenceModule(IntelligenceModule):
    key = "sentiment_intelligence"
    title = "Sentiment intelligence"
    question = "Why are they buying?"
    business_output = "Customer sentiment"
    reads = "Reviews, social comments, feedback"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.feedback.empty:
            return self.empty("No customer feedback captured in this period.")

        fb = d.feedback
        counts = fb["sentiment"].value_counts()
        total = len(fb)
        pos = int(counts.get("positive", 0))
        neg = int(counts.get("negative", 0))
        score = round(pos / total * 100, 1)

        prior_score = 0.0
        if not d.prior_feedback.empty:
            pc = d.prior_feedback["sentiment"].value_counts()
            prior_score = round(int(pc.get("positive", 0)) / len(d.prior_feedback) * 100, 1)

        by_source = fb.groupby("source").agg(
            volume=("feedback_id", "count"), avg_score=("sentiment_score", "mean")
        ).reset_index().sort_values("volume", ascending=False)

        by_store = pd.DataFrame()
        if fb["store_id"].notna().any():
            by_store = fb.dropna(subset=["store_id"]).groupby("store_id").agg(
                volume=("feedback_id", "count"), avg_score=("sentiment_score", "mean"),
                negative=("sentiment", lambda s: int((s == "negative").sum())),
            ).reset_index()
            by_store["negative_pct"] = (by_store["negative"] / by_store["volume"] * 100).round(1)
            by_store["store_name"] = by_store["store_id"].map(d.store_name)
            by_store = by_store.sort_values("negative_pct", ascending=False)

        daily = fb.groupby("date").agg(
            volume=("feedback_id", "count"), score=("sentiment_score", "mean")).reset_index()

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "interactions": total,
                "sentiment_score_pct": score,
                "sentiment_delta_pct": self.pct_change(score, prior_score) if prior_score else 0.0,
                "negative_count": neg,
                "negative_share_pct": round(neg / total * 100, 1),
                "sources": int(fb["source"].nunique()),
            },
            series=[
                Series(name="Daily sentiment",
                       points=[{"label": str(r["date"]), "value": round(float(r["score"]) * 100, 1)}
                               for _, r in daily.iterrows()], unit="%"),
                Series(name="Volume by source",
                       points=[{"label": r["source"], "value": int(r["volume"])}
                               for _, r in by_source.iterrows()], unit="mentions"),
            ],
            tables={
                "by_source": by_source.round(3).to_dict("records"),
                "by_store": by_store.head(15).drop(columns=["store_id"], errors="ignore")
                            .round(2).to_dict("records") if not by_store.empty else [],
                "recent_negative": fb[fb["sentiment"] == "negative"]
                                   .nlargest(10, "captured_at")[["source", "body", "rating", "themes"]]
                                   .to_dict("records"),
            },
        )

        if prior_score and abs(self.pct_change(score, prior_score)) >= 5:
            delta = self.pct_change(score, prior_score)
            worst_source = by_source.nsmallest(1, "avg_score")
            src = str(worst_source.iloc[0]["source"]) if not worst_source.empty else ""
            result.findings.append(Finding(
                headline=f"Sentiment moved {delta:+.1f}% to {score}% positive across "
                         f"{total:,} interactions.",
                reasoning=(
                    f"The prior period scored {prior_score}%. "
                    + (f"The weakest channel is {src}, which is where the shift concentrates. "
                       if src else "")
                    + "Sentiment is a leading indicator: it moves before repeat rate does, which "
                    "is why it is worth acting on before the sales number confirms it."
                ),
                actions=[
                    Action(f"Read the {src} negatives in full this week — volume tells you "
                           "something changed, the text tells you what." if src else
                           "Read this period's negative verbatims in full.",
                           owner="operations", effort="low", horizon="this week"),
                    Action("Re-measure in two weeks against this baseline and record the outcome "
                           "on this insight.", owner="marketing", effort="low", horizon="in two weeks"),
                ],
                kind="anomaly" if abs(delta) >= 10 else "explanation",
                severity="high" if delta <= -10 else "medium",
                confidence=0.75, metric_value=score, metric_delta_pct=delta,
            ))

        if not by_store.empty and len(by_store) >= 3:
            worst = by_store.iloc[0]
            network_neg = neg / total * 100
            if worst["negative_pct"] >= network_neg * 1.5 and worst["volume"] >= 5:
                result.findings.append(Finding(
                    headline=f"{worst['store_name']} runs {worst['negative_pct']:.0f}% negative "
                             f"against a network average of {network_neg:.0f}%.",
                    reasoning=(
                        f"{int(worst['volume'])} pieces of feedback from this store, "
                        f"{int(worst['negative'])} of them negative. A store this far off the "
                        "network norm is usually an execution problem at that site rather than a "
                        "brand-level issue — the same menu and the same pricing perform differently "
                        "elsewhere."
                    ),
                    actions=[Action(
                        f"Send the {worst['store_name']} verbatims to the area manager and ask for "
                        "a response within the week, rather than routing it through a brand review.",
                        owner="operations", effort="low", horizon="this week")],
                    kind="risk", severity="high", confidence=0.78,
                    metric_value=float(worst["negative_pct"]), store_id=str(worst["store_id"]),
                ))

        result.narrative = (
            f"{total:,} customer interactions in {ctx.label()}, {score}% positive, "
            f"{neg} negative."
        )
        return result


class VoiceOfCustomerModule(IntelligenceModule):
    key = "voice_of_customer"
    title = "Voice of customer"
    question = "What is stopping them?"
    business_output = "Customer pain points"
    reads = "Complaints, requests, suggestions"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.feedback.empty:
            return self.empty("No customer feedback captured in this period.")

        fb = d.feedback
        themes = Counter()
        theme_sentiment: dict[str, list[float]] = {}
        theme_rows: dict[str, list[dict]] = {}

        for _, row in fb.iterrows():
            for t in [x.strip() for x in str(row["themes"]).split(",") if x.strip()]:
                themes[t] += 1
                theme_sentiment.setdefault(t, []).append(float(row["sentiment_score"]))
                theme_rows.setdefault(t, []).append({
                    "source": row["source"], "body": str(row["body"])[:220],
                    "sentiment": row["sentiment"],
                    "store": d.store_name(row["store_id"]) if pd.notna(row["store_id"]) else "",
                })

        if not themes:
            return self.empty("Feedback is present but not yet themed.")

        prior_themes = Counter()
        if not d.prior_feedback.empty:
            for t in d.prior_feedback["themes"].fillna(""):
                prior_themes.update([x.strip() for x in str(t).split(",") if x.strip()])
        n_cur, n_prior = len(fb), max(len(d.prior_feedback), 1)

        rows = []
        for theme, count in themes.most_common(25):
            avg_sent = sum(theme_sentiment[theme]) / len(theme_sentiment[theme])
            cur_rate, prior_rate = count / n_cur, prior_themes.get(theme, 0) / n_prior
            rows.append({
                "theme": theme, "mentions": count,
                "share_pct": round(cur_rate * 100, 1),
                "avg_sentiment": round(avg_sent, 3),
                "momentum_pct": self.pct_change(cur_rate, prior_rate),
                "is_pain_point": avg_sent < 0.4,
            })

        pains = [r for r in rows if r["is_pain_point"]]
        pains.sort(key=lambda r: (r["mentions"], -r["avg_sentiment"]), reverse=True)

        # Time-of-day concentration — the doc's "delivery complaints rose in the 7–9 PM window".
        window_note = ""
        if pains and not fb.empty:
            top_theme = pains[0]["theme"]
            hits = fb[fb["themes"].fillna("").str.contains(top_theme, case=False, regex=False)]
            if len(hits) >= 5:
                hours = pd.to_datetime(hits["captured_at"]).dt.hour
                peak = int(hours.mode().iloc[0])
                share = float((hours.between(peak - 1, peak + 1)).mean())
                if share >= 0.35:
                    window_note = (
                        f"{share:.0%} of these mentions land between "
                        f"{peak - 1:02d}:00 and {peak + 2:02d}:00."
                    )

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "themes_detected": len(themes),
                "pain_points": len(pains),
                "top_pain_point": pains[0]["theme"] if pains else "—",
                "top_pain_mentions": pains[0]["mentions"] if pains else 0,
                "interactions": n_cur,
            },
            series=[Series(
                name="Mentions by theme",
                points=[{"label": r["theme"], "value": r["mentions"]} for r in rows[:8]],
                unit="mentions")],
            tables={
                "themes": rows,
                "pain_points": pains[:10],
                "verbatims": {t: theme_rows[t][:5] for t in list(theme_rows)[:8]},
            },
        )

        if pains:
            p = pains[0]
            examples = theme_rows[p["theme"]][:3]
            result.findings.append(Finding(
                headline=f"'{p['theme']}' is the most frequent pain point, in {p['mentions']} of "
                         f"{n_cur:,} interactions.",
                reasoning=(
                    f"Average sentiment on this theme is {p['avg_sentiment']:.2f} against a neutral "
                    f"midpoint of 0.5, and mentions moved {p['momentum_pct']:+.0f}% against the "
                    f"prior period. {window_note} "
                    "Complaint themes are ranked by volume and sentiment together, because a rare "
                    "complaint at very low sentiment and a common complaint at mild sentiment need "
                    "different responses."
                ).strip(),
                actions=[
                    Action(f"Give '{p['theme']}' an owner and a target this week — it is the single "
                           "highest-volume complaint, so it is also the cheapest to move.",
                           owner="operations", effort="medium", horizon="this week"),
                    Action("Track the theme's mention share weekly and record the change against "
                           "this insight once the fix has landed.",
                           owner="operations", effort="low", horizon="in one month"),
                ],
                kind="risk", severity="high" if p["share_pct"] >= 15 else "medium",
                confidence=0.8, metric_value=float(p["mentions"]),
                metric_delta_pct=p["momentum_pct"],
                evidence={"examples": examples, "window": window_note},
            ))

        surging = [r for r in rows if r["momentum_pct"] >= 40 and r["mentions"] >= 4]
        if surging:
            s = surging[0]
            result.findings.append(Finding(
                headline=f"'{s['theme']}' mentions are up {s['momentum_pct']:.0f}% on the prior "
                         "period.",
                reasoning=(
                    f"{s['mentions']} mentions this period at {s['share_pct']}% of all feedback. "
                    "A theme growing this fast is worth catching before it reaches the volume that "
                    "makes it a top complaint — the response is cheaper at this stage."
                ),
                actions=[Action(
                    f"Read the '{s['theme']}' verbatims now and confirm whether this is a new "
                    "operational change or a seasonal pattern before responding.",
                    owner="operations", effort="low", horizon="this week")],
                kind="trend", severity="medium", confidence=0.65,
                metric_value=float(s["mentions"]), metric_delta_pct=s["momentum_pct"],
            ))

        result.narrative = (
            f"{len(themes)} themes across {n_cur:,} interactions. "
            + (f"The leading pain point is '{pains[0]['theme']}'." if pains else
               "No theme scored below the pain-point threshold.")
        )
        return result


class CompetitorIntelligenceModule(IntelligenceModule):
    key = "competitor_intelligence"
    title = "Competitor intelligence"
    question = "What is stopping them?"
    business_output = "Competitive positioning"
    reads = "Reviews, menus, offers, public digital signals"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data
        if d.competitor_signals.empty:
            return self.empty(
                "No competitor signals collected for this period. Connect a review or listening "
                "source in Settings → Data sources."
            )

        cs = d.competitor_signals
        by_comp = cs.groupby("competitor_name").agg(
            signals=("signal_type", "count"),
            avg_sentiment=("sentiment", lambda s: float((s == "positive").mean())),
            price_points=("price_point", "mean"),
        ).reset_index().sort_values("signals", ascending=False)
        by_comp["positive_pct"] = (by_comp["avg_sentiment"] * 100).round(1)

        by_type = cs["signal_type"].value_counts().reset_index()
        by_type.columns = ["signal_type", "signals"]

        # Our own price position, if the tenant has products in comparable ranges.
        our_avg = float(d.products[d.products["is_active"]]["price"].mean()) if not d.products.empty else 0.0
        their_avg = float(cs["price_point"].dropna().mean()) if cs["price_point"].notna().any() else 0.0

        # What customers praise competitors for is where our own gap is.
        praise_themes = Counter()
        for _, r in cs[cs["sentiment"] == "positive"].iterrows():
            for w in str(r["body"]).lower().split():
                w = w.strip(".,!?-")
                if len(w) > 4 and w not in _STOPWORDS:
                    praise_themes[w] += 1

        result = ModuleResult(
            module_key=self.key, title=self.title, business_output=self.business_output,
            headline_metrics={
                "competitors_tracked": int(cs["competitor_name"].nunique()),
                "signals": int(len(cs)),
                "our_avg_price": round(our_avg, 0),
                "competitor_avg_price": round(their_avg, 0),
                "price_gap_pct": self.pct_change(our_avg, their_avg) if their_avg else 0.0,
            },
            series=[Series(
                name="Signals by competitor",
                points=[{"label": r["competitor_name"], "value": int(r["signals"])}
                        for _, r in by_comp.head(6).iterrows()], unit="signals")],
            tables={
                "competitors": by_comp.round(1).to_dict("records"),
                "signal_types": by_type.to_dict("records"),
                "recent_offers": cs[cs["signal_type"].isin(["offer", "price"])]
                                 .nlargest(10, "observed_at")[
                                     ["competitor_name", "signal_type", "body", "price_point", "city"]
                                 ].to_dict("records"),
                "praise_words": [{"word": w, "mentions": c} for w, c in praise_themes.most_common(12)],
            },
        )

        if their_avg and our_avg:
            gap = self.pct_change(our_avg, their_avg)
            if abs(gap) >= 8:
                above = gap > 0
                result.findings.append(Finding(
                    headline=f"Our average price sits {abs(gap):.0f}% "
                             f"{'above' if above else 'below'} the tracked competitor set.",
                    reasoning=(
                        f"Our active catalogue averages {self.money(our_avg, ctx.currency)} against "
                        f"{self.money(their_avg, ctx.currency)} across "
                        f"{int(cs['price_point'].notna().sum())} observed competitor price points. "
                        + ("A premium is defensible only if customers can name what they get for it; "
                           "check whether our sentiment advantage justifies the gap."
                           if above else
                           "Pricing below the set leaves margin on the table unless the volume "
                           "advantage is real and measured.")
                    ),
                    actions=[Action(
                        "Compare our sentiment score against the competitor set before changing "
                        "price — if we lead on sentiment, the premium is earned; if we do not, the "
                        "gap is a leak.", owner="pricing", effort="medium", horizon="this month")],
                    kind="risk" if above else "opportunity",
                    severity="medium", confidence=0.6, metric_value=round(our_avg, 0),
                    metric_delta_pct=gap,
                ))

        strongest = by_comp[by_comp["signals"] >= 3].nlargest(1, "positive_pct")
        if not strongest.empty:
            s = strongest.iloc[0]
            top_words = ", ".join(w for w, _ in praise_themes.most_common(3))
            result.findings.append(Finding(
                headline=f"{s['competitor_name']} scores {s['positive_pct']:.0f}% positive across "
                         f"{int(s['signals'])} public signals.",
                reasoning=(
                    f"The words customers use most about them are: {top_words or 'not yet distinct'}. "
                    "Competitor praise is the cheapest source of a product gap — it tells you what "
                    "customers value in the category without having to run research."
                ),
                actions=[Action(
                    f"Test whether our own feedback contains the same words. If it does not, that "
                    "is the gap worth closing first.",
                    owner="category", effort="low", horizon="this month")],
                kind="opportunity", severity="medium", confidence=0.55,
                metric_value=float(s["positive_pct"]),
                evidence={"praise": praise_themes.most_common(8)},
            ))

        result.narrative = (
            f"{int(cs['competitor_name'].nunique())} competitors tracked across {len(cs)} public "
            f"signals in {ctx.label()}."
        )
        return result


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "they", "there", "their", "have", "has",
    "was", "were", "been", "from", "very", "just", "really", "here", "about", "would",
    "could", "your", "them", "then", "than", "into", "over", "when", "what", "which",
    "always", "never", "also", "more", "most", "some", "such", "only", "much", "many",
}
