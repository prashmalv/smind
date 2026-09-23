"""The module registry, and the run that produces the daily shopper pulse.

Thirteen modules come straight from the concept doc. `store_vision` is the fourteenth,
added because the platform now has cameras.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from app.intelligence.base import AnalysisContext, IntelligenceModule, ModuleResult, json_safe
from app.intelligence.modules_customer import (
    ChurnIntelligenceModule,
    CustomerProfilingModule,
    NextBestOfferModule,
    PurchaseBehaviorModule,
)
from app.intelligence.modules_listening import (
    CompetitorIntelligenceModule,
    SentimentIntelligenceModule,
    VoiceOfCustomerModule,
)
from app.intelligence.modules_operations import (
    CampaignIntelligenceModule,
    StoreIntelligenceModule,
    StoreVisionModule,
)
from app.intelligence.modules_product import (
    BasketAnalysisModule,
    MenuIntelligenceModule,
    PriceSensitivityModule,
    TrendDetectionModule,
)

log = logging.getLogger(__name__)

MODULES: tuple[IntelligenceModule, ...] = (
    CustomerProfilingModule(),
    PurchaseBehaviorModule(),
    MenuIntelligenceModule(),
    BasketAnalysisModule(),
    SentimentIntelligenceModule(),
    VoiceOfCustomerModule(),
    CampaignIntelligenceModule(),
    StoreIntelligenceModule(),
    PriceSensitivityModule(),
    CompetitorIntelligenceModule(),
    TrendDetectionModule(),
    ChurnIntelligenceModule(),
    NextBestOfferModule(),
    StoreVisionModule(),
)

BY_KEY: dict[str, IntelligenceModule] = {m.key: m for m in MODULES}

# Which of the doc's five questions each module answers — used by the copilot to pick
# modules from a natural-language question.
QUESTION_MAP: dict[str, list[str]] = {}
for _m in MODULES:
    QUESTION_MAP.setdefault(_m.question, []).append(_m.key)


def catalogue() -> list[dict]:
    """The module directory the UI renders on the Modules page."""
    return [
        {
            "key": m.key,
            "title": m.title,
            "question": m.question,
            "business_output": m.business_output,
            "reads": m.reads,
            "verticals": list(m.verticals) or ["all"],
        }
        for m in MODULES
    ]


def run_module(key: str, ctx: AnalysisContext) -> ModuleResult:
    module = BY_KEY.get(key)
    if module is None:
        raise KeyError(f"Unknown module '{key}'")
    if not module.applies_to(ctx.vertical):
        return module.empty(f"{module.title} does not apply to the {ctx.vertical} vertical.")
    try:
        return module.run(ctx)
    except Exception:  # a failing module must not take the whole run down
        log.exception("module %s failed for tenant %s", key, ctx.tenant_id)
        return module.empty(f"{module.title} could not complete on this period's data.")


def run_all(ctx: AnalysisContext, keys: list[str] | None = None) -> dict[str, ModuleResult]:
    """Run modules against one shared Dataset.

    The frames are built lazily and cached on the context, so the first module pays the
    query cost and the rest read from memory. Threads are safe here because the work after
    the first module is pure pandas.
    """
    selected = keys or [m.key for m in MODULES]
    # Every query happens here, on this thread. See Dataset.warm().
    ctx.data.warm()

    results: dict[str, ModuleResult] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(run_module, k, ctx): k for k in selected}
        for fut, key in futures.items():
            results[key] = fut.result()
    return {k: results[k] for k in selected if k in results}


def persist_findings(ctx: AnalysisContext, results: dict[str, ModuleResult]) -> int:
    """Write each finding into `insights` so the loop can be closed later.

    Re-running a module the same day replaces that day's rows rather than duplicating —
    an insight is a statement about a period, not an event.
    """
    from sqlalchemy import delete

    from app.models.intelligence import Insight

    written = 0
    day_start = ctx.period_end.replace(hour=0, minute=0, second=0, microsecond=0)

    for key, res in results.items():
        if not res.findings:
            continue
        ctx.db.execute(
            delete(Insight)
            .where(Insight.tenant_id == ctx.tenant_id)
            .where(Insight.module_key == key)
            .where(Insight.detected_at >= day_start)
            .where(Insight.status == "new")
        )
        for f in res.findings:
            ctx.db.add(Insight(
                tenant_id=ctx.tenant_id, module_key=key, kind=f.kind, severity=f.severity,
                confidence=f.confidence, headline=f.headline[:300], reasoning=f.reasoning,
                actions=json.dumps([a.__dict__ for a in f.actions]),
                evidence=json.dumps(f.evidence, default=str)[:20000],
                store_id=f.store_id, product_id=f.product_id,
                metric_value=f.metric_value, metric_delta_pct=f.metric_delta_pct,
                estimated_impact=f.estimated_impact, detected_at=ctx.period_end, status="new",
            ))
            written += 1
    ctx.db.commit()
    return written


def shopper_pulse(ctx: AnalysisContext) -> dict:
    """The command-center home screen: today's pulse in six numbers and four signals."""
    results = run_all(ctx, [
        "purchase_behavior", "customer_profiling", "sentiment_intelligence",
        "voice_of_customer", "trend_detection", "basket_analysis", "menu_intelligence",
        "store_vision",
    ])

    pb = results["purchase_behavior"].headline_metrics
    cp = results["customer_profiling"].headline_metrics
    si = results["sentiment_intelligence"].headline_metrics
    voc = results["voice_of_customer"].headline_metrics
    td = results["trend_detection"].headline_metrics
    ba = results["basket_analysis"].tables.get("rules", [])
    mi = results["menu_intelligence"].headline_metrics
    sv = results["store_vision"].headline_metrics

    repeat_rate = 0.0
    if not ctx.data.orders.empty:
        per_customer = ctx.data.orders.dropna(subset=["customer_id"]).groupby("customer_id").size()
        if len(per_customer):
            repeat_rate = round(float((per_customer > 1).mean()) * 100, 1)

    all_findings = [
        {**f.to_dict(), "module_key": key}
        for key, res in results.items() for f in res.findings
    ]
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_findings.sort(key=lambda f: (severity_rank.get(f["severity"], 9), -f["confidence"]))

    # Four signals that each say something different. Without this, the top trend and
    # the top complaint can be the same theme, and the cross-sell suggestion can be the
    # product already named as high-performing — four cards carrying two facts.
    top_item = mi.get("top_item", "—")
    top_pain = voc.get("top_pain_point", "—")
    used = {v for v in (top_item, top_pain) if v and v != "—"}

    trend = td.get("top_trend", "—")
    if trend in used:
        alternatives = [
            r["item"] for r in results["trend_detection"].tables.get("rising", [])
        ] + [
            r["theme"]
            for r in results["trend_detection"].tables.get("conversation_trends", [])
            # Only genuinely positive language counts as an emerging preference.
            if r.get("avg_sentiment", 0.5) >= 0.5
        ]
        trend = next((a for a in alternatives if a not in used), "—")
    if trend != "—":
        used.add(trend)

    cross_sell = "—"
    for rule in ba:
        if rule["consequent"] not in used:
            cross_sell = rule["consequent"]
            break

    return json_safe({
        "period": {"label": ctx.label(), "days": ctx.period_days,
                   "end": ctx.period_end.isoformat()},
        "metrics": [
            {"label": "Active customers", "value": cp.get("active_customers", 0),
             "format": "count", "delta_pct": None},
            {"label": "Average basket", "value": pb.get("avg_basket", 0),
             "format": "currency", "delta_pct": pb.get("basket_delta_pct")},
            {"label": "Repeat rate", "value": repeat_rate, "format": "percent",
             "delta_pct": None},
            {"label": "Customer sentiment", "value": si.get("sentiment_score_pct", 0),
             "format": "percent", "delta_pct": si.get("sentiment_delta_pct")},
        ],
        "secondary_metrics": [
            {"label": "Revenue", "value": pb.get("revenue", 0), "format": "currency",
             "delta_pct": pb.get("revenue_delta_pct")},
            {"label": "Orders", "value": pb.get("orders", 0), "format": "count",
             "delta_pct": None},
            {"label": "Footfall", "value": sv.get("footfall", 0), "format": "count",
             "delta_pct": None},
            {"label": "Queue wait", "value": sv.get("avg_wait_seconds", 0), "format": "seconds",
             "delta_pct": None},
        ],
        "signals": [
            {"label": "Emerging trend", "value": trend, "module": "trend_detection"},
            {"label": "Rising concern", "value": top_pain, "module": "voice_of_customer"},
            {"label": "Cross-sell opportunity", "value": cross_sell,
             "module": "basket_analysis"},
            {"label": "High-performing product", "value": top_item,
             "module": "menu_intelligence"},
        ],
        "findings": all_findings[:8],
        "suggested_questions": [
            "Why are customers choosing competitors?",
            "Which products should we promote?",
            "What is driving today's sales?",
            "What are customers saying about our new product?",
            "Which stores need attention?",
        ],
    })
