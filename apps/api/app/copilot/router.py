"""Question → modules, without a model.

Two jobs. It is the whole routing layer when Azure OpenAI is not configured, and it is a
hint to the model when it is — a small nudge costs nothing and stops the model running
competitor intelligence when someone asked about queues.
"""

from __future__ import annotations

import re

# Ordered: the first pattern that matches wins the primary module, and the rest of its
# modules come along as supporting context. Order encodes specificity, not importance.
ROUTES: list[tuple[str, list[str]]] = [
    (r"\b(queue|wait|waiting|footfall|walk[- ]?in|dwell|camera|crowd|occupancy|abandon)",
     ["store_vision", "store_intelligence"]),
    (r"\b(churn|lapsed|lost customer|stopped (ordering|buying)|not (come|coming) back|retention|win[- ]?back)",
     ["churn_intelligence", "customer_profiling"]),
    (r"\b(offer|recommend|next best|personalis|personaliz|what should we (offer|give|send))",
     ["next_best_offer", "customer_profiling", "basket_analysis"]),
    (r"\b(competitor|rival|versus|vs\.?\s|market share|others are|competing)",
     ["competitor_intelligence", "price_sensitivity", "sentiment_intelligence"]),
    # Placed above pricing on purpose: "what should we promote" is a merchandising
    # question, and the word "promote" would otherwise pull it into price sensitivity.
    (r"\b(what|which).{0,24}\b(promote|feature|push|highlight|showcase|advertise)\b",
     ["menu_intelligence", "basket_analysis", "next_best_offer", "trend_detection"]),
    (r"\b(price|pricing|discount|cheap|expensive|margin|elasticit|increase the price)",
     ["price_sensitivity", "campaign_intelligence", "menu_intelligence"]),
    (r"\b(campaign|offer perform|roi|return on|marketing spend|redemption|budget)",
     ["campaign_intelligence", "next_best_offer"]),
    (r"\b(complain|complaint|issue|problem|pain|unhappy|angry|dissatisf|what.*wrong)",
     ["voice_of_customer", "sentiment_intelligence"]),
    (r"\b(sentiment|review|feeling|saying about|opinion|feedback|rating|nps)",
     ["sentiment_intelligence", "voice_of_customer"]),
    (r"\b(together|combo|bundle|cross[- ]?sell|attach|pair|add[- ]?on|upsell)",
     ["basket_analysis", "next_best_offer", "menu_intelligence"]),
    (r"\b(trend|emerging|new product|what.?s (hot|rising|popular)|demand shift|launch)",
     ["trend_detection", "menu_intelligence"]),
    (r"\b(store|location|outlet|branch|city|region|which stores|site)",
     ["store_intelligence", "store_vision"]),
    (r"\b(segment|who (is|are) (buying|our)|profile|customer type|demographic|audience)",
     ["customer_profiling", "purchase_behavior"]),
    (r"\b(menu|item|product|sku|dish|best sell|worst sell|selling|catalogue|catalog)",
     ["menu_intelligence", "purchase_behavior", "basket_analysis"]),
    (r"\b(sales|revenue|decline|drop|fell|fall|grew|growth|down|up|performance|basket|aov)",
     ["purchase_behavior", "menu_intelligence", "store_intelligence"]),
]

SIMULATION_PATTERN = re.compile(
    r"\b(what if|what happens if|simulate|scenario|if we (raise|increase|cut|drop|launch|"
    r"introduce|remove|delist|bundle)|suppose we|impact of (raising|cutting|launching))",
    re.IGNORECASE,
)


def route(question: str) -> list[str]:
    """Pick the modules most likely to hold the answer. Never returns empty."""
    q = question.lower()
    picked: list[str] = []
    for pattern, modules in ROUTES:
        if re.search(pattern, q):
            for m in modules:
                if m not in picked:
                    picked.append(m)
        if len(picked) >= 4:
            break
    if not picked:
        # "How are we doing?" — the general health question.
        picked = ["purchase_behavior", "customer_profiling", "sentiment_intelligence"]
    return picked[:4]


def is_simulation(question: str) -> bool:
    return bool(SIMULATION_PATTERN.search(question))


def extract_period_days(question: str, default: int = 30) -> int:
    """Read a period out of the question — people say 'this month', not 'period_days=30'."""
    q = question.lower()
    if re.search(r"\b(today|so far today)\b", q):
        return 1
    if re.search(r"\b(yesterday)\b", q):
        return 2
    if re.search(r"\b(this week|last 7|past week|weekly)\b", q):
        return 7
    if re.search(r"\b(fortnight|last 14|two weeks)\b", q):
        return 14
    if re.search(r"\b(quarter|last 90|three months|3 months)\b", q):
        return 90
    if re.search(r"\b(year|last 365|12 months|annual)\b", q):
        return 365
    match = re.search(r"\blast (\d{1,3}) days?\b", q)
    if match:
        return max(1, min(int(match.group(1)), 730))
    return default
