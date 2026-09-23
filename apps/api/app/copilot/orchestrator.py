"""The copilot loop: question in, grounded answer out.

With Azure OpenAI configured this is a tool-calling loop. Without it, `_compose_locally`
builds the same shape of answer directly from module findings — what happened, why, what
to do. The local answer is less fluent and it does not handle a follow-up as gracefully,
but it is grounded in exactly the same numbers, which is the part that matters.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.copilot.prompts import SIMULATION_PROMPT, SYSTEM_PROMPT, VOICE_SUFFIX
from app.copilot.router import extract_period_days, is_simulation, route
from app.copilot.tools import build_tool_schemas, execute_tool
from app.intelligence.base import AnalysisContext, json_safe
from app.intelligence.registry import BY_KEY, run_all
from app.services.azure_openai import openai_client, parse_tool_calls

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3


@dataclass
class CopilotAnswer:
    text: str
    modules_used: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    latency_ms: int = 0
    engine: str = "local"


async def answer(
    question: str,
    ctx: AnalysisContext,
    tenant_name: str,
    history: list[dict] | None = None,
    is_voice: bool = False,
) -> CopilotAnswer:
    started = time.monotonic()
    ctx.period_days = extract_period_days(question, ctx.period_days)

    if openai_client.enabled:
        try:
            result = await _answer_with_model(question, ctx, tenant_name, history or [], is_voice)
            result.latency_ms = int((time.monotonic() - started) * 1000)
            return result
        except Exception:
            log.exception("Azure OpenAI path failed; falling back to the local reasoner")

    result = _compose_locally(question, ctx, is_voice)
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


# ── model path ──────────────────────────────────────────────────────────────
async def _answer_with_model(
    question: str, ctx: AnalysisContext, tenant_name: str,
    history: list[dict], is_voice: bool,
) -> CopilotAnswer:
    system = SYSTEM_PROMPT.format(
        tenant_name=tenant_name, vertical=ctx.vertical, country="India",
        today=date.today().isoformat(), currency=ctx.currency,
    )
    if is_simulation(question):
        system += "\n\n" + SIMULATION_PROMPT.format(tenant_name=tenant_name)
    if is_voice:
        system += VOICE_SUFFIX

    hint = route(question)
    system += (
        f"\n\nRouting hint for this question — these modules most likely hold the answer: "
        f"{', '.join(hint)}. Use your own judgement if the question suggests otherwise."
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})

    tools = build_tool_schemas()
    modules_used: list[str] = []
    evidence: dict[str, Any] = {}

    for _ in range(MAX_TOOL_ROUNDS):
        message = await openai_client.chat(messages, tools=tools)
        calls = parse_tool_calls(message)
        if not calls:
            return _finalize(
                str(message.get("content") or ""), modules_used, evidence, ctx, question,
                engine="azure-openai",
            )

        messages.append({
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls"),
        })
        for call_id, tool_name, args in calls:
            payload, keys = execute_tool(tool_name, args, ctx)
            modules_used.extend(k for k in keys if k not in modules_used)
            try:
                evidence[tool_name] = json.loads(payload)
            except json.JSONDecodeError:
                evidence[tool_name] = {"raw": payload[:2000]}
            messages.append({"role": "tool", "tool_call_id": call_id, "content": payload})

    # Tool budget spent — ask for the answer with what is already on the table.
    messages.append({
        "role": "user",
        "content": "Answer now using the tool results above. Do not call any more tools.",
    })
    final = await openai_client.chat(messages, tools=None)
    return _finalize(
        str(final.get("content") or ""), modules_used, evidence, ctx, question,
        engine="azure-openai",
    )


# ── local path ──────────────────────────────────────────────────────────────
def _compose_locally(question: str, ctx: AnalysisContext, is_voice: bool) -> CopilotAnswer:
    """Build the three-movement answer straight from module findings."""
    if is_simulation(question):
        return _compose_simulation_locally(question, ctx)

    keys = route(question)
    results = run_all(ctx, keys)

    findings = [
        {**f.to_dict(), "module_key": key}
        for key, res in results.items() for f in res.findings
    ]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (rank.get(f["severity"], 9), -f["confidence"]))

    primary = BY_KEY[keys[0]]
    primary_result = results[keys[0]]

    if not findings:
        note = primary_result.coverage_note or primary_result.narrative
        text = (
            f"I ran {primary.title.lower()} over {ctx.label()} and nothing crossed the "
            f"threshold worth flagging. {note} "
            "Either the period is genuinely stable, or the source feeding this module is not "
            "connected yet — check Settings → Data sources."
        )
        return CopilotAnswer(text=text, modules_used=keys,
                             evidence=json_safe({k: v.headline_metrics for k, v in results.items()}),
                             charts=_charts(results),
                             followups=_followups(keys, question))

    top = findings[0]
    parts = [top["headline"], top["reasoning"]]

    actions = top.get("actions") or []
    if actions:
        action_text = " ".join(
            f"{a['text']}"
            + (f" (expected: {a['expected_impact']})" if a.get("expected_impact") else "")
            for a in actions[:2]
        )
        parts.append(f"What to do: {action_text}")

    if len(findings) > 1 and not is_voice:
        others = "; ".join(f["headline"] for f in findings[1:3])
        parts.append(f"Also worth knowing — {others}")

    if primary_result.coverage_note and "not" in primary_result.coverage_note.lower():
        parts.append(primary_result.coverage_note)

    text = " ".join(parts)
    if is_voice:
        from app.services.azure_speech import spoken_form

        text = spoken_form(text, ctx.currency)

    return CopilotAnswer(
        text=text, modules_used=keys, findings=findings[:5],
        evidence=json_safe({k: v.headline_metrics for k, v in results.items()}),
        charts=_charts(results), followups=_followups(keys, question),
    )


def _compose_simulation_locally(question: str, ctx: AnalysisContext) -> CopilotAnswer:
    from app.simulator.engine import parse_question, run_scenario

    params = parse_question(question, ctx)
    outcome = run_scenario(
        ctx, scenario_type=params["scenario_type"], target=params["target"],
        magnitude=params["magnitude"],
    )
    return CopilotAnswer(
        text=outcome.get("narrative", "The scenario could not be estimated on this data."),
        modules_used=["shopper_simulator"], evidence={"simulation": outcome},
        charts=outcome.get("charts", []),
        followups=[
            "What would happen at half that change?",
            "Which stores would be most affected?",
            "Which customer segments carry the most risk here?",
        ],
    )


# ── shared ──────────────────────────────────────────────────────────────────
def _finalize(
    text: str, modules_used: list[str], evidence: dict, ctx: AnalysisContext,
    question: str, engine: str,
) -> CopilotAnswer:
    findings: list[dict] = []
    charts: list[dict] = []
    for payload in evidence.values():
        if not isinstance(payload, dict):
            continue
        blocks = [payload] if "findings" in payload else list(payload.values())
        for block in blocks:
            if isinstance(block, dict):
                findings.extend(block.get("findings") or [])
                for s in block.get("series") or []:
                    charts.append(s)
    return CopilotAnswer(
        text=text.strip(), modules_used=modules_used, evidence=evidence,
        findings=findings[:5], charts=charts[:4],
        followups=_followups(modules_used or route(question), question), engine=engine,
    )


def _charts(results: dict) -> list[dict]:
    out = []
    for res in results.values():
        for s in res.series[:2]:
            if s.points:
                out.append({"name": s.name, "points": s.points[:24], "unit": s.unit})
    return out[:4]


_FOLLOWUPS = {
    "purchase_behavior": ["Which stores drove that?", "Was it volume or basket size?"],
    "menu_intelligence": ["Which items should we delist?", "What is our margin mix by category?"],
    "basket_analysis": ["What bundle should we test first?", "Which stores have the lowest attachment?"],
    "sentiment_intelligence": ["Which store has the worst sentiment?", "What changed since last month?"],
    "voice_of_customer": ["Show me the verbatims for that theme", "Is that complaint rising or falling?"],
    "campaign_intelligence": ["Which campaign should we stop?", "Where should that budget go instead?"],
    "store_intelligence": ["Which stores need attention?", "How does conversion compare across the estate?"],
    "price_sensitivity": ["What if we raise the price by 10%?", "Which items can take a price rise?"],
    "competitor_intelligence": ["How do our prices compare?", "What are customers praising them for?"],
    "trend_detection": ["Should we launch something around that?", "Is it showing up in sales yet?"],
    "churn_intelligence": ["Who should we win back first?", "What is the revenue at risk?"],
    "next_best_offer": ["Which offers should we push this week?", "What is the expected uplift?"],
    "customer_profiling": ["Which segment is growing?", "Where is our revenue concentrated?"],
    "store_vision": ["When are queues worst?", "Which stores lose customers to the queue?"],
}


def _followups(keys: list[str], asked: str = "") -> list[str]:
    """Suggest what to ask next — never the question just asked."""
    def normalise(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    already = normalise(asked)
    out: list[str] = []
    for k in keys:
        for q in _FOLLOWUPS.get(k, []):
            if q not in out and normalise(q) != already:
                out.append(q)
    return out[:4]
