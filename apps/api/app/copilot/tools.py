"""The tools the copilot can call. Each one wraps a real module run.

The copilot has no direct database access by design: it can only see what a module returns,
so every number it states is traceable to a module and a period. That is what makes the
audit trail on each message meaningful.
"""

from __future__ import annotations

import json
from typing import Any

from app.intelligence.base import AnalysisContext
from app.intelligence.registry import BY_KEY, catalogue, run_module
from app.services.azure_openai import tool_schema

_PERIOD = {
    "type": "integer",
    "description": "Days to analyse, counting back from today. Defaults to 30.",
}
_STORES = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Optional store names or codes to narrow the analysis to.",
}


def build_tool_schemas() -> list[dict[str, Any]]:
    modules = catalogue()
    module_list = "; ".join(f"{m['key']} ({m['business_output']})" for m in modules)
    return [
        tool_schema(
            "run_module",
            "Run one shopper intelligence module and get its metrics, tables and findings. "
            f"Available modules: {module_list}.",
            {
                "module_key": {
                    "type": "string",
                    "enum": [m["key"] for m in modules],
                    "description": "Which module to run.",
                },
                "period_days": _PERIOD,
                "store_filter": _STORES,
            },
            ["module_key"],
        ),
        tool_schema(
            "run_modules",
            "Run several modules at once when a question spans more than one area — for "
            "example a sales decline that needs purchase behaviour, menu intelligence and "
            "voice of customer together. Prefer this over several separate calls.",
            {
                "module_keys": {
                    "type": "array",
                    "items": {"type": "string", "enum": [m["key"] for m in modules]},
                    "description": "Two to four modules. More than four returns too much to reason over.",
                },
                "period_days": _PERIOD,
                "store_filter": _STORES,
            },
            ["module_keys"],
        ),
        tool_schema(
            "simulate",
            "Estimate the outcome of a decision before it is made: a price change, a new "
            "value item, a bundle, or a promotion. Returns demand, basket, margin and "
            "segment impact estimated from this business's own history.",
            {
                "scenario_type": {
                    "type": "string",
                    "enum": ["price_change", "new_item", "bundle", "promotion", "delist"],
                },
                "target": {
                    "type": "string",
                    "description": "The product, category or bundle the scenario applies to.",
                },
                "magnitude": {
                    "type": "number",
                    "description": "Price change amount, new item price, or discount percent, "
                                   "depending on scenario_type.",
                },
                "period_days": _PERIOD,
            },
            ["scenario_type", "target"],
        ),
        tool_schema(
            "get_context",
            "Get the business's shape: stores, catalogue size, date coverage, which data "
            "sources are connected. Call this first when a question names something you "
            "cannot resolve, such as an unfamiliar store or product.",
            {},
            [],
        ),
    ]


def _trim(result_dict: dict, max_rows: int = 12) -> dict:
    """Keep tool results inside a sane token budget without losing the findings.

    Findings are never trimmed — they are the answer. Tables are, because the model needs
    a few representative rows, not the whole frame.
    """
    out = dict(result_dict)
    out["tables"] = {
        name: (rows[:max_rows] if isinstance(rows, list) else rows)
        for name, rows in result_dict.get("tables", {}).items()
        if not name.startswith("_")
    }
    out["series"] = [
        {**s, "points": s["points"][:24]} for s in result_dict.get("series", [])
    ]
    return out


def execute_tool(name: str, args: dict, ctx: AnalysisContext) -> tuple[str, list[str]]:
    """Run a tool. Returns (json_payload_for_the_model, module_keys_touched)."""
    period = int(args.get("period_days") or ctx.period_days)
    store_filter = args.get("store_filter") or None
    run_ctx = AnalysisContext(
        db=ctx.db, tenant_id=ctx.tenant_id, period_days=period, period_end=ctx.period_end,
        store_ids=_resolve_stores(ctx, store_filter), currency=ctx.currency,
        vertical=ctx.vertical,
    )

    if name == "run_module":
        key = args.get("module_key", "")
        if key not in BY_KEY:
            return json.dumps({"error": f"Unknown module '{key}'"}), []
        res = run_module(key, run_ctx)
        return json.dumps(_trim(res.to_dict()), default=str), [key]

    if name == "run_modules":
        keys = [k for k in (args.get("module_keys") or []) if k in BY_KEY][:4]
        if not keys:
            return json.dumps({"error": "No valid module keys supplied"}), []
        payload = {k: _trim(run_module(k, run_ctx).to_dict(), max_rows=8) for k in keys}
        return json.dumps(payload, default=str), keys

    if name == "simulate":
        from app.simulator.engine import run_scenario

        outcome = run_scenario(
            run_ctx,
            scenario_type=args.get("scenario_type", "price_change"),
            target=args.get("target", ""),
            magnitude=float(args.get("magnitude") or 0),
        )
        return json.dumps(outcome, default=str), ["shopper_simulator"]

    if name == "get_context":
        return json.dumps(business_context(run_ctx), default=str), []

    return json.dumps({"error": f"Unknown tool '{name}'"}), []


def _resolve_stores(ctx: AnalysisContext, names: list[str] | None) -> list[str] | None:
    """Turn store names the user typed into ids. A name the user got slightly wrong should
    still resolve — they are speaking, not querying."""
    if not names:
        return ctx.store_ids
    stores = ctx.data.stores
    if stores.empty:
        return ctx.store_ids
    wanted = {n.strip().lower() for n in names}
    hits = stores[
        stores["store_name"].str.lower().isin(wanted)
        | stores["code"].str.lower().isin(wanted)
        | stores["city"].str.lower().isin(wanted)
    ]
    if hits.empty:
        hits = stores[
            stores["store_name"].str.lower().apply(lambda s: any(w in s for w in wanted))
        ]
    return hits["store_id"].tolist() or ctx.store_ids


def business_context(ctx: AnalysisContext) -> dict:
    """What the copilot needs to know before it can interpret a question."""
    d = ctx.data
    connected = {
        "orders": not d.orders.empty,
        "catalogue": not d.products.empty,
        "customers": not d.customers.empty,
        "feedback": not d.feedback.empty,
        "campaigns": not d.campaigns.empty,
        "competitor_signals": not d.competitor_signals.empty,
        "cameras": not d.camera_events.empty,
    }
    return {
        "period": ctx.label(),
        "currency": ctx.currency,
        "vertical": ctx.vertical,
        "stores": d.stores[["store_name", "city", "format"]].head(40).to_dict("records")
        if not d.stores.empty else [],
        "store_count": int(len(d.stores)),
        "catalogue_size": int(len(d.products)),
        "categories": sorted(d.products["category"].dropna().unique().tolist())[:30]
        if not d.products.empty else [],
        "orders_in_period": int(len(d.orders)),
        "customers_on_file": int(len(d.customers)),
        "data_sources_connected": connected,
        "missing_sources": [k for k, v in connected.items() if not v],
    }
