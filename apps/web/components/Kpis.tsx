"use client";

import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import { formatMetric, percent } from "@/lib/api";

export type MetricT = {
  label: string;
  value: number | string | null;
  format: string;
  delta_pct?: number | null;
};

/**
 * Colour never carries the meaning alone — the direction arrow is the primary signal and
 * the colour reinforces it, so the delta reads for a colour-blind viewer and in print.
 */
export function Kpis({ metrics, currency = "INR" }: { metrics: MetricT[]; currency?: string }) {
  return (
    <div className="kpis">
      {metrics.map((m) => {
        const d = m.delta_pct;
        const hasDelta = typeof d === "number" && Number.isFinite(d) && d !== 0;
        const Icon = !hasDelta ? Minus : d! > 0 ? TrendingUp : TrendingDown;
        return (
          <div className="kpi" key={m.label}>
            <p className="u-eyebrow u-eyebrow--muted">{m.label}</p>
            <p className="u-stat kpi__value">
              {formatMetric(m.value as number, m.format, currency)}
            </p>
            <p
              className={
                "kpi__delta" +
                (hasDelta ? (d! < 0 ? " kpi__delta--bad" : " kpi__delta--good") : "")
              }
            >
              <Icon size={13} />
              {hasDelta ? `${d! > 0 ? "+" : ""}${percent(d!)} vs prior` : "no prior comparison"}
            </p>
          </div>
        );
      })}
    </div>
  );
}
