"use client";

/**
 * Shopper Simulator — test the decision before you make it.
 *
 * Every result shows its assumptions and its confidence next to the number. A simulated
 * figure presented with the same authority as an observed one is how forecasting tools
 * lose their users.
 */

import { useEffect, useState } from "react";

import { Chart } from "@/components/Chart";
import { DataTable } from "@/components/DataTable";
import { api, getTenant, money } from "@/lib/api";

type Scenario = { key: string; label: string; example: string; evaluates: string[] };
type Outcome = {
  scenario_type: string; target: string; magnitude: number;
  results: Record<string, unknown>;
  narrative: string; confidence: number;
  assumptions?: string[];
  charts?: { name: string; points: { label: string; value: number }[]; unit: string }[];
  run_id?: string;
};

export default function Simulator() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [question, setQuestion] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<Outcome[]>([]);
  const currency = getTenant()?.currency ?? "INR";

  useEffect(() => {
    api<{ scenarios: Scenario[] }>("/api/v1/simulator/scenarios")
      .then((d) => setScenarios(d.scenarios))
      .catch(() => setScenarios([]));
    api<Outcome[]>("/api/v1/simulator/runs").then(setHistory).catch(() => setHistory([]));
  }, []);

  async function run(q: string) {
    if (!q.trim()) return;
    setBusy(true);
    setOutcome(null);
    try {
      const res = await api<Outcome>("/api/v1/simulator/run", {
        method: "POST",
        body: { question: q, period_days: 30, save: true },
      });
      setOutcome(res);
      setHistory(await api<Outcome[]>("/api/v1/simulator/runs"));
    } finally {
      setBusy(false);
    }
  }

  const resultRows = outcome
    ? Object.entries(outcome.results)
        .filter(([, v]) => typeof v === "number" || typeof v === "string" || typeof v === "boolean")
        .map(([k, v]) => ({
          measure: k.replace(/_/g, " "),
          value: typeof v === "number" ? v : String(v),
        }))
    : [];

  const nestedTables = outcome
    ? Object.entries(outcome.results).filter(
        ([, v]) => Array.isArray(v) && v.length > 0 && typeof v[0] === "object",
      )
    : [];

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">Shopper Simulator</p>
        <h1 className="u-display">Test the decision before you make it</h1>
        <p className="u-lede">
          Ask a what-if question and ShopperMind estimates the outcome from your own
          history — demand, basket, margin, segment and store-level impact.
        </p>
      </header>

      <form
        className="composer__row"
        style={{ marginBottom: "var(--s-5)" }}
        onSubmit={(e) => { e.preventDefault(); run(question); }}
      >
        <input
          className="input" value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What happens if we increase the combo price by ₹20?"
          aria-label="What-if question"
        />
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Simulating…" : "Simulate"}
        </button>
      </form>

      <div className="filters">
        {scenarios.map((s) => (
          <button
            key={s.key} className="btn btn--ghost btn--sm"
            onClick={() => { setQuestion(s.example); run(s.example); }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {outcome && (
        <section className="section">
          <div className="section__head">
            <h2 className="section__title">
              {outcome.scenario_type.replace(/_/g, " ")} · {outcome.target}
            </h2>
            <span className="u-mono" style={{ color: "var(--ink-3)" }}>
              confidence {Math.round(outcome.confidence * 100)}%
            </span>
          </div>

          <p className="u-measure" style={{ fontSize: "17px", color: "var(--ink-2)" }}>
            {outcome.narrative}
          </p>

          {outcome.confidence < 0.5 && (
            <p className="hint" style={{ marginTop: "var(--s-3)" }}>
              This is an estimate with wide error bars. Treat the direction as informative
              and the magnitude as indicative — and pilot it before rolling it out.
            </p>
          )}

          {outcome.charts?.map((c, i) => (
            <Chart
              key={c.name} title={c.name} points={c.points} unit={c.unit}
              kind="bar" colorIndex={i}
              source={`Source: simulated from your last 30 days · confidence ${Math.round(outcome.confidence * 100)}%`}
            />
          ))}

          {outcome.assumptions && outcome.assumptions.length > 0 && (
            <div style={{ borderLeft: "1px solid var(--rule)", paddingLeft: "var(--s-4)", marginTop: "var(--s-5)" }}>
              <p className="u-eyebrow">What this assumes</p>
              <ul style={{ marginTop: "var(--s-2)", paddingLeft: "var(--s-5)" }}>
                {outcome.assumptions.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}

          {resultRows.length > 0 && (
            <div className="section">
              <h3 className="section__title" style={{ marginBottom: "var(--s-3)" }}>
                The numbers
              </h3>
              <DataTable
                columns={[
                  { key: "measure", label: "Measure", format: "text" },
                  { key: "value", label: "Value", format: "text" },
                ]}
                rows={resultRows.map((r) => ({
                  measure: r.measure,
                  value: typeof r.value === "number"
                    ? (/revenue|margin|impact|price|risk|retained|lost|cost/.test(r.measure)
                        ? money(r.value, currency)
                        : r.value.toLocaleString())
                    : r.value,
                }))}
                currency={currency}
              />
            </div>
          )}

          {nestedTables.map(([name, rows]) => {
            const list = rows as Record<string, unknown>[];
            return (
              <div className="section" key={name}>
                <h3 className="section__title" style={{ marginBottom: "var(--s-3)" }}>
                  {name.replace(/_/g, " ")}
                </h3>
                <DataTable
                  columns={Object.keys(list[0]).map((k) => ({
                    key: k,
                    label: k.replace(/_/g, " "),
                    format: (typeof list[0][k] === "number" ? "number" : "text") as "number" | "text",
                  }))}
                  rows={list}
                  currency={currency}
                />
              </div>
            );
          })}

          {outcome.run_id && (
            <button
              className="btn btn--ghost btn--sm"
              style={{ marginTop: "var(--s-5)" }}
              onClick={() =>
                api(`/api/v1/simulator/runs/${outcome.run_id}/executed`, { method: "PATCH" })
              }
            >
              We went ahead with this
            </button>
          )}
        </section>
      )}

      <section className="section">
        <div className="section__head">
          <h2 className="section__title">What each scenario evaluates</h2>
        </div>
        <div className="grid-2">
          {scenarios.map((s) => (
            <div key={s.key}>
              <p className="u-eyebrow">{s.label}</p>
              <p className="hint" style={{ margin: "var(--s-2) 0" }}>{s.example}</p>
              <ul style={{ paddingLeft: "var(--s-5)", fontSize: "14px" }}>
                {s.evaluates.map((e) => <li key={e}>{e}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {history.length > 0 && (
        <section className="section">
          <div className="section__head">
            <h2 className="section__title">Previous simulations</h2>
          </div>
          <DataTable
            columns={[
              { key: "question", label: "Question", format: "text" },
              { key: "scenario_type", label: "Type", format: "text" },
              { key: "confidence", label: "Confidence", format: "decimal" },
            ]}
            rows={history.slice(0, 10) as unknown as Record<string, unknown>[]}
            currency={currency}
          />
        </section>
      )}
    </div>
  );
}
