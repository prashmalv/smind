"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Chart } from "@/components/Chart";
import { DataTable } from "@/components/DataTable";
import { Finding, type FindingT } from "@/components/Finding";
import { PeriodPicker } from "@/components/PeriodPicker";
import { api, formatMetric, getTenant } from "@/lib/api";

type Result = {
  module_key: string;
  title: string;
  business_output: string;
  headline_metrics: Record<string, number | string | null>;
  series: { name: string; points: { label: string; value: number }[]; unit: string }[];
  tables: Record<string, Record<string, unknown>[]>;
  findings: FindingT[];
  narrative: string;
  coverage_note: string;
};

/** Metric keys that are money, percentages or seconds — everything else is a count. */
function formatOf(key: string): string {
  if (/revenue|value|spend|impact|basket|price|risk|discount|uplift/.test(key)) return "currency";
  if (/pct|rate|share|percent|margin/.test(key)) return "percent";
  if (/seconds/.test(key)) return "seconds";
  return "count";
}

function columnsFor(rows: Record<string, unknown>[]) {
  if (!rows.length) return [];
  return Object.keys(rows[0])
    .filter((k) => !k.startsWith("_"))
    .slice(0, 8)
    .map((k) => {
      const sample = rows.find((r) => r[k] !== null && r[k] !== undefined)?.[k];
      const numeric = typeof sample === "number";
      return {
        key: k,
        label: k.replace(/_/g, " ").replace(/\bpct\b/, "%"),
        format: (numeric
          ? /revenue|value|amount|budget|impact|basket|price|margin(?!_pct)/.test(k)
            ? "currency"
            : /pct|rate|share/.test(k)
              ? "percent"
              : Number.isInteger(sample as number)
                ? "number"
                : "decimal"
          : "text") as "text" | "currency" | "number" | "percent" | "decimal",
      };
    });
}

export default function ModuleDetail() {
  const { key } = useParams<{ key: string }>();
  const [days, setDays] = useState(30);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const currency = getTenant()?.currency ?? "INR";

  const load = useCallback(async (period: number) => {
    setError(null);
    setResult(null);
    try {
      setResult(await api<Result>(`/api/v1/intelligence/modules/${key}?period_days=${period}`));
    } catch {
      setError("That module could not be run. It may need a data source you have not connected.");
    }
  }, [key]);

  useEffect(() => { load(days); }, [days, load]);

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">
          <Link href="/modules">Modules</Link> · {result?.business_output ?? ""}
        </p>
        <h1 className="u-display">{result?.title ?? String(key).replace(/_/g, " ")}</h1>
        {result?.narrative && <p className="u-lede">{result.narrative}</p>}
      </header>

      <PeriodPicker value={days} onChange={setDays} />

      {error && <p className="error">{error}</p>}
      {!result && !error && <p className="loading">Running the module…</p>}

      {result && (
        <>
          {result.coverage_note && (
            <p className="hint" style={{ marginBottom: "var(--s-5)" }}>{result.coverage_note}</p>
          )}

          {Object.keys(result.headline_metrics).length > 0 && (
            <div className="tiles tiles--4">
              {Object.entries(result.headline_metrics).slice(0, 8).map(([k, v]) => (
                <div className="tile" key={k}>
                  <p className="u-eyebrow u-eyebrow--muted">
                    {k.replace(/_/g, " ").replace(/\bpct\b/, "%")}
                  </p>
                  <p className="tile__value" style={{ marginTop: "var(--s-2)" }}>
                    {formatMetric(v as number, formatOf(k), currency)}
                  </p>
                </div>
              ))}
            </div>
          )}

          {result.series.length > 0 && (
            <section className="section">
              <div className="grid-2">
                {result.series.map((s, i) => (
                  <Chart
                    key={s.name}
                    title={s.name}
                    points={s.points}
                    unit={s.unit}
                    kind={s.points.length > 12 ? "line" : "bar"}
                    colorIndex={i}
                  />
                ))}
              </div>
            </section>
          )}

          <section className="section">
            <div className="section__head">
              <h2 className="section__title">Findings</h2>
              <span className="u-eyebrow u-eyebrow--muted">
                insight · reason · action
              </span>
            </div>
            {result.findings.length === 0 ? (
              <div className="empty">
                <p>
                  Nothing in this module crossed the threshold worth flagging over{" "}
                  {days} days. The metrics above are still live — a quiet module is a
                  result, not a failure.
                </p>
              </div>
            ) : (
              result.findings.map((f, i) => (
                <Finding key={i} finding={{ ...f, module_title: result.title }} currency={currency} />
              ))
            )}
          </section>

          {Object.entries(result.tables)
            .filter(([name, rows]) => !name.startsWith("_") && Array.isArray(rows) && rows.length > 0)
            .map(([name, rows]) => (
              <section className="section" key={name}>
                <div className="section__head">
                  <h2 className="section__title">{name.replace(/_/g, " ")}</h2>
                  <span className="u-eyebrow u-eyebrow--muted">{rows.length} rows</span>
                </div>
                <DataTable columns={columnsFor(rows)} rows={rows.slice(0, 25)} currency={currency} />
              </section>
            ))}
        </>
      )}
    </div>
  );
}
