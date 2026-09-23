"use client";

/**
 * A finding, rendered as the concept doc's chain: insight → reason → action.
 *
 * The three parts are visually distinct on purpose. A dashboard shows the first part
 * and stops; showing all three in one block is the product's whole argument, so the
 * layout should not let a reader skip to the number and leave.
 */

import { money, percent } from "@/lib/api";

export type ActionT = {
  text: string; owner: string; effort: string;
  expected_impact?: string; horizon: string;
};

export type FindingT = {
  headline: string;
  reasoning: string;
  actions: ActionT[];
  kind: string;
  severity: string;
  confidence: number;
  metric_value?: number | null;
  metric_delta_pct?: number | null;
  estimated_impact?: number | null;
  module_key?: string;
  module_title?: string;
  id?: string;
  status?: string;
};

export function Finding({
  finding, currency = "INR", onAcknowledge,
}: {
  finding: FindingT;
  currency?: string;
  onAcknowledge?: (id: string, status: string) => void;
}) {
  const delta = finding.metric_delta_pct;
  return (
    <article className="finding">
      <div className="finding__meta">
        <span className={`sev sev--${finding.severity}`}>{finding.severity}</span>
        <span className="u-eyebrow u-eyebrow--muted">
          {finding.module_title ?? finding.module_key?.replace(/_/g, " ") ?? finding.kind}
        </span>
        <span className="u-mono" style={{ color: "var(--ink-3)" }}>
          confidence {Math.round(finding.confidence * 100)}%
        </span>
        {typeof delta === "number" && delta !== 0 && (
          <span className={`u-mono ${delta < 0 ? "kpi__delta--bad" : "kpi__delta--good"}`}>
            {delta > 0 ? "+" : ""}{percent(delta)}
          </span>
        )}
        {typeof finding.estimated_impact === "number" && finding.estimated_impact > 0 && (
          <span className="u-mono" style={{ color: "var(--ink-3)" }}>
            est. {money(finding.estimated_impact, currency)}
          </span>
        )}
      </div>

      <h3 className="finding__headline">{finding.headline}</h3>
      <p className="finding__why">{finding.reasoning}</p>

      {finding.actions.length > 0 && (
        <div className="finding__actions">
          <p className="u-eyebrow" style={{ marginBottom: "var(--s-3)" }}>What to do</p>
          {finding.actions.map((a, i) => (
            <p className="finding__action" key={i}>
              <strong>{a.text}</strong>{" "}
              <span className="u-mono" style={{ color: "var(--ink-3)" }}>
                {a.owner} · {a.horizon} · {a.effort} effort
                {a.expected_impact ? ` · ${a.expected_impact}` : ""}
              </span>
            </p>
          ))}
        </div>
      )}

      {onAcknowledge && finding.id && (
        <div className="filters" style={{ marginTop: "var(--s-4)", marginBottom: 0 }}>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => onAcknowledge(finding.id!, "acknowledged")}
            disabled={finding.status !== "new"}
          >
            {finding.status === "new" ? "Acknowledge" : "Acknowledged"}
          </button>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => onAcknowledge(finding.id!, "actioned")}
            disabled={finding.status === "actioned" || finding.status === "measured"}
          >
            Mark actioned
          </button>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => onAcknowledge(finding.id!, "dismissed")}
          >
            Dismiss
          </button>
        </div>
      )}
    </article>
  );
}
