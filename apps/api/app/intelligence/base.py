"""The contract every intelligence module honours.

The concept doc draws one line: Data → Insight → Reason → Action → Measurement. A module
that only emits metrics stops at step 2 and is just a dashboard. So `Finding` requires a
`reasoning` string and at least one `action` — a module cannot report a number without
saying why it moved and what to do about it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class AnalysisContext:
    """Everything a module is allowed to see. `tenant_id` is the isolation boundary."""

    db: Session
    tenant_id: str
    period_days: int = 30
    period_end: datetime = field(default_factory=lambda: datetime.now(UTC))
    store_ids: list[str] | None = None
    currency: str = "INR"
    vertical: str = "qsr"
    _dataset: Any = field(default=None, repr=False, compare=False)

    @property
    def data(self):
        """Period frames, built once and shared by every module in the run."""
        if self._dataset is None:
            from app.intelligence.dataset import Dataset

            self._dataset = Dataset(self)
        return self._dataset

    @property
    def period_start(self) -> datetime:
        return self.period_end - timedelta(days=self.period_days)

    @property
    def prior_start(self) -> datetime:
        return self.period_start - timedelta(days=self.period_days)

    @property
    def prior_end(self) -> datetime:
        return self.period_start

    def label(self) -> str:
        return f"{self.period_start:%d %b} – {self.period_end:%d %b %Y}"


@dataclass
class Action:
    """Something a human can actually do on Monday morning."""

    text: str
    owner: str = "marketing"           # marketing | operations | category | store | pricing
    effort: str = "low"                # low | medium | high
    expected_impact: str = ""
    horizon: str = "this week"


@dataclass
class Finding:
    headline: str                       # 2. Insight — what happened
    reasoning: str                      # 3. Reason — why it happened
    actions: list[Action]               # 4. Action — what to do
    kind: str = "explanation"           # opportunity | risk | anomaly | trend | explanation
    severity: str = "medium"            # low | medium | high | critical
    confidence: float = 0.6
    evidence: dict[str, Any] = field(default_factory=dict)
    metric_value: float | None = None
    metric_delta_pct: float | None = None
    estimated_impact: float | None = None
    store_id: str | None = None
    product_id: str | None = None

    def __post_init__(self) -> None:
        if not self.actions:
            raise ValueError(
                f"Finding '{self.headline[:50]}' has no action. "
                "A module must not report a number without a recommendation."
            )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actions"] = [asdict(a) for a in self.actions]
        return json_safe(d)


def json_safe(value: Any) -> Any:
    """Make pandas output safe to serialise.

    NaN and infinity are legal floats in pandas and illegal in JSON, and they turn up
    honestly — a store with no camera has no conversion rate. Rather than defending
    against it in fourteen modules, every result passes through here once, and a missing
    number reaches the UI as null so it can be rendered as "no data" instead of zero.
    """
    import math

    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    # numpy scalars, pandas NaT, Decimal, dates — normalise through their Python form.
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (ValueError, AttributeError):
            pass
    if value != value:  # NaT and other self-unequal sentinels
        return None
    return value


@dataclass
class Series:
    """A named line/bar series ready for the dashboard, with its own labels."""

    name: str
    points: list[dict[str, Any]]
    x_key: str = "label"
    y_key: str = "value"
    unit: str = ""


@dataclass
class ModuleResult:
    module_key: str
    title: str
    business_output: str
    headline_metrics: dict[str, Any] = field(default_factory=dict)
    series: list[Series] = field(default_factory=list)
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    narrative: str = ""
    coverage_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return json_safe({
            "module_key": self.module_key,
            "title": self.title,
            "business_output": self.business_output,
            "headline_metrics": self.headline_metrics,
            "series": [asdict(s) for s in self.series],
            "tables": self.tables,
            "findings": [f.to_dict() for f in self.findings],
            "narrative": self.narrative,
            "coverage_note": self.coverage_note,
        })


class IntelligenceModule(ABC):
    """Base class. Subclasses declare their identity, then implement `run`."""

    key: str = ""
    title: str = ""
    question: str = ""            # which of the five questions this module answers
    business_output: str = ""
    reads: str = ""               # what the module analyses, in the doc's words
    verticals: tuple[str, ...] = ()   # empty means every vertical
    min_rows: int = 1             # below this, the module reports insufficient data

    @abstractmethod
    def run(self, ctx: AnalysisContext) -> ModuleResult:
        ...

    # ── helpers shared by every module ──────────────────────────────────────
    def empty(self, note: str = "Not enough data in this period.") -> ModuleResult:
        return ModuleResult(
            module_key=self.key,
            title=self.title,
            business_output=self.business_output,
            narrative=note,
            coverage_note=note,
        )

    @staticmethod
    def pct_change(current: float, prior: float) -> float:
        if prior == 0:
            return 0.0 if current == 0 else 100.0
        return round((current - prior) / abs(prior) * 100, 2)

    @staticmethod
    def money(value: float, currency: str = "INR") -> str:
        symbol = {"INR": "₹", "USD": "$", "AED": "AED ", "GBP": "£"}.get(currency, "")
        return f"{symbol}{value:,.0f}"

    def applies_to(self, vertical: str) -> bool:
        return not self.verticals or vertical in self.verticals
