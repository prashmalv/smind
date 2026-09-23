"""The seven behavioural segments from the concept doc.

A customer is never permanently assigned. Each profiling run re-scores everyone, and the
recommended response moves with them — which is why `SegmentAssignment` keeps the previous
key: segment *movement* is itself an insight.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    key: str
    label: str
    who: str
    respond_with: str
    priority: int


SEGMENTS: tuple[Segment, ...] = (
    Segment("value_seekers", "Value seekers", "Price-sensitive customers",
            "Bundles and discounts", 40),
    Segment("convenience_seekers", "Convenience seekers",
            "Focused on quick ordering and delivery", "Express ordering", 50),
    Segment("frequency_customers", "Frequency customers", "High-repeat customers",
            "Loyalty and personalised rewards", 70),
    Segment("premium_customers", "Premium customers",
            "Higher order value, premium products", "Premium combos and limited editions", 80),
    Segment("occasional_customers", "Occasional customers", "Low visit frequency",
            "Re-engagement campaigns", 30),
    Segment("lapsed_customers", "Lapsed customers", "Previously active, now inactive",
            "Win-back campaigns", 60),
    Segment("product_loyalists", "Product loyalists",
            "Strong affinity to particular products", "Product-specific recommendations", 55),
)

BY_KEY = {s.key: s for s in SEGMENTS}


def label(key: str) -> str:
    seg = BY_KEY.get(key)
    return seg.label if seg else key.replace("_", " ").title()


def response_for(key: str) -> str:
    seg = BY_KEY.get(key)
    return seg.respond_with if seg else "Personalised recommendations"
