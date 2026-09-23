"use client";

/**
 * The insight loop, including the step most analytics products never build: recording
 * what actually happened after the action was taken, and scoring the platform against it.
 */

import { useCallback, useEffect, useState } from "react";

import { Finding, type FindingT } from "@/components/Finding";
import { api, getTenant, percent } from "@/lib/api";

type Insight = FindingT & {
  id: string; status: string; detected_at: string; module_title: string;
  outcome_note: string; outcome_delta_pct: number | null;
};

type Measurement = {
  total_insights: number; actioned: number; measured: number;
  action_rate_pct: number; hit_rate_pct: number; avg_outcome_delta_pct: number;
  by_module: { module_key: string; insights: number; measured: number; avg_delta_pct: number }[];
};

const STATUSES = ["new", "acknowledged", "actioned", "measured", "dismissed"];

export default function Insights() {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const currency = getTenant()?.currency ?? "INR";

  const load = useCallback(async () => {
    const qs = filter ? `?status=${filter}` : "";
    const [rows, m] = await Promise.all([
      api<Insight[]>(`/api/v1/intelligence/insights${qs}`),
      api<Measurement>("/api/v1/intelligence/insights/measurement"),
    ]);
    setInsights(rows);
    setMeasurement(m);
  }, [filter]);

  useEffect(() => { load().catch(() => setInsights([])); }, [load]);

  async function refresh() {
    setBusy(true);
    setNote(null);
    try {
      const res = await api<{ insights_written: number; modules_run: number }>(
        "/api/v1/intelligence/refresh",
        { method: "POST", body: { period_days: 30 } },
      );
      setNote(
        `Ran ${res.modules_run} modules and recorded ${res.insights_written} findings. `
        + "Segments, churn scores and offers were refreshed too.",
      );
      await load();
    } catch {
      setNote("The refresh could not complete. Analyst role or above is required.");
    } finally {
      setBusy(false);
    }
  }

  async function update(id: string, status: string) {
    await api(`/api/v1/intelligence/insights/${id}`, { method: "PATCH", body: { status } });
    await load();
  }

  async function recordOutcome(id: string, delta: number, text: string) {
    await api(`/api/v1/intelligence/insights/${id}`, {
      method: "PATCH",
      body: { outcome_note: text, outcome_delta_pct: delta },
    });
    await load();
  }

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">Data · insight · reason · action · measurement</p>
        <h1 className="u-display">Insights</h1>
        <p className="u-lede">
          Every finding the modules have produced, and what happened after you acted on it.
          The last column is the one that makes the next run better.
        </p>
      </header>

      {measurement && (
        <div className="kpis">
          <div className="kpi">
            <p className="u-eyebrow u-eyebrow--muted">Insights recorded</p>
            <p className="u-stat kpi__value">{measurement.total_insights}</p>
            <p className="kpi__delta">across all modules</p>
          </div>
          <div className="kpi">
            <p className="u-eyebrow u-eyebrow--muted">Action rate</p>
            <p className="u-stat kpi__value">{percent(measurement.action_rate_pct)}</p>
            <p className="kpi__delta">{measurement.actioned} acted on</p>
          </div>
          <div className="kpi">
            <p className="u-eyebrow u-eyebrow--muted">Hit rate</p>
            <p className="u-stat kpi__value">
              {measurement.measured ? percent(measurement.hit_rate_pct) : "—"}
            </p>
            <p className="kpi__delta">
              {measurement.measured
                ? `${measurement.measured} measured`
                : "record an outcome to score it"}
            </p>
          </div>
          <div className="kpi">
            <p className="u-eyebrow u-eyebrow--muted">Average outcome</p>
            <p className="u-stat kpi__value">
              {measurement.measured ? percent(measurement.avg_outcome_delta_pct, 2) : "—"}
            </p>
            <p className="kpi__delta">after the action landed</p>
          </div>
        </div>
      )}

      <div className="filters" style={{ marginTop: "var(--s-6)" }}>
        <button
          className="btn btn--ghost btn--sm" aria-pressed={filter === ""}
          onClick={() => setFilter("")}
        >
          All
        </button>
        {STATUSES.map((s) => (
          <button
            key={s} className="btn btn--ghost btn--sm" aria-pressed={filter === s}
            onClick={() => setFilter(s)}
          >
            {s}
          </button>
        ))}
        <button className="btn btn--sm" onClick={refresh} disabled={busy}>
          {busy ? "Running all modules…" : "Refresh intelligence"}
        </button>
      </div>

      {note && <p className="hint" style={{ marginBottom: "var(--s-5)" }}>{note}</p>}

      {insights.length === 0 ? (
        <div className="empty">
          <p>
            No insights stored yet. Run <strong>Refresh intelligence</strong> to execute all
            fourteen modules and record what they find.
          </p>
        </div>
      ) : (
        insights.map((ins) => (
          <div key={ins.id}>
            <Finding finding={ins} currency={currency} onAcknowledge={update} />
            {(ins.status === "actioned" || ins.status === "measured") && (
              <OutcomeForm insight={ins} onSave={recordOutcome} />
            )}
          </div>
        ))
      )}
    </div>
  );
}

function OutcomeForm({
  insight, onSave,
}: {
  insight: Insight;
  onSave: (id: string, delta: number, note: string) => Promise<void>;
}) {
  const [delta, setDelta] = useState(insight.outcome_delta_pct?.toString() ?? "");
  const [text, setText] = useState(insight.outcome_note ?? "");
  const [saved, setSaved] = useState(false);

  return (
    <form
      style={{
        borderLeft: "1px solid var(--rule)",
        paddingLeft: "var(--s-4)",
        margin: "calc(var(--s-5) * -1) 0 var(--s-5)",
      }}
      onSubmit={async (e) => {
        e.preventDefault();
        await onSave(insight.id, Number(delta), text);
        setSaved(true);
      }}
    >
      <p className="u-eyebrow">Measurement — what actually happened</p>
      <div style={{ display: "flex", gap: "var(--s-3)", marginTop: "var(--s-3)", flexWrap: "wrap" }}>
        <input
          className="input" style={{ maxWidth: "140px" }} type="number" step="0.1"
          value={delta} onChange={(e) => setDelta(e.target.value)}
          placeholder="% change" aria-label="Outcome percentage change"
        />
        <input
          className="input" style={{ flex: 1, minWidth: "240px" }}
          value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Moved the evening shift; wait fell to 70s" aria-label="Outcome note"
        />
        <button className="btn btn--sm" type="submit">Record outcome</button>
      </div>
      {saved && <p className="hint">Recorded. This now counts towards the hit rate above.</p>}
    </form>
  );
}
