"use client";

/**
 * The command center: today's shopper pulse at a glance, with a prompt bar underneath
 * for follow-up questions — the landing view described in the concept doc.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Chart } from "@/components/Chart";
import { Finding, type FindingT } from "@/components/Finding";
import { Kpis, type MetricT } from "@/components/Kpis";
import { PeriodPicker } from "@/components/PeriodPicker";
import { api, formatMetric, getTenant } from "@/lib/api";

type Pulse = {
  period: { label: string; days: number };
  metrics: MetricT[];
  secondary_metrics: MetricT[];
  signals: { label: string; value: string; module: string }[];
  findings: FindingT[];
  suggested_questions: string[];
};

export default function CommandCenter() {
  const router = useRouter();
  const [days, setDays] = useState(30);
  const [pulse, setPulse] = useState<Pulse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const currency = getTenant()?.currency ?? "INR";

  const load = useCallback(async (period: number) => {
    setError(null);
    try {
      setPulse(await api<Pulse>(`/api/v1/intelligence/pulse?period_days=${period}`));
    } catch {
      setError("Could not load the shopper pulse. Check that the API is reachable.");
    }
  }, []);

  useEffect(() => { load(days); }, [days, load]);

  const ask = (q: string) => {
    if (!q.trim()) return;
    router.push(`/ask?q=${encodeURIComponent(q)}`);
  };

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">Shopper AI command center</p>
        <h1 className="u-display">Today&rsquo;s shopper pulse</h1>
        <p className="u-lede">
          {pulse ? pulse.period.label : "Loading"} · everything below is computed from your
          own data, and every finding names what to do about it.
        </p>
      </header>

      <PeriodPicker value={days} onChange={setDays} />

      {error && <p className="error">{error}</p>}
      {!pulse && !error && <p className="loading">Reading your data…</p>}

      {pulse && (
        <>
          <Kpis metrics={pulse.metrics} currency={currency} />

          <div className="tiles tiles--4" style={{ marginTop: "var(--s-5)" }}>
            {pulse.secondary_metrics.map((m) => (
              <div className="tile" key={m.label}>
                <p className="u-eyebrow u-eyebrow--muted">{m.label}</p>
                <p className="tile__value" style={{ marginTop: "var(--s-2)" }}>
                  {formatMetric(m.value as number, m.format, currency)}
                </p>
              </div>
            ))}
          </div>

          <div className="signals" style={{ marginTop: "var(--s-6)" }}>
            {pulse.signals.map((s) => (
              <div className="signal" key={s.label}>
                <p className="u-eyebrow u-eyebrow--muted">{s.label}</p>
                <p className="signal__value">{s.value}</p>
                <Link
                  href={`/modules/${s.module}`}
                  className="u-mono"
                  style={{ display: "inline-block", marginTop: "var(--s-2)" }}
                >
                  {s.module.replace(/_/g, " ")} →
                </Link>
              </div>
            ))}
          </div>

          <section className="section">
            <div className="section__head">
              <h2 className="section__title">Ask ShopperMind</h2>
              <Link href="/ask" className="u-mono">Open the full conversation →</Link>
            </div>
            <form
              className="composer__row"
              onSubmit={(e) => { e.preventDefault(); ask(question); }}
              style={{ marginBottom: "var(--s-4)" }}
            >
              <input
                className="input"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Why did sales fall this month?"
                aria-label="Ask ShopperMind a question"
              />
              <button className="btn" type="submit">Ask</button>
            </form>
            <div className="filters">
              {pulse.suggested_questions.map((q) => (
                <button key={q} className="btn btn--ghost btn--sm" onClick={() => ask(q)}>
                  {q}
                </button>
              ))}
            </div>
          </section>

          <section className="section">
            <div className="section__head">
              <h2 className="section__title">What needs attention</h2>
              <Link href="/insights" className="u-mono">All insights →</Link>
            </div>
            {pulse.findings.length === 0 ? (
              <div className="empty">
                <p>
                  Nothing crossed the threshold worth flagging in this period. That is a
                  real result, not an empty screen — either the estate is stable, or a
                  source is not connected yet.
                </p>
                <p style={{ marginTop: "var(--s-3)" }}>
                  <Link href="/data">Check your data sources →</Link>
                </p>
              </div>
            ) : (
              pulse.findings.map((f, i) => (
                <Finding key={i} finding={f} currency={currency} />
              ))
            )}
          </section>
        </>
      )}
    </div>
  );
}
