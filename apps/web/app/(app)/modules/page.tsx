"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

type ModuleT = {
  key: string; title: string; question: string;
  business_output: string; reads: string;
};
type Catalogue = {
  vertical: string;
  modules: ModuleT[];
  by_question: Record<string, ModuleT[]>;
  segments: { key: string; label: string; who: string; respond_with: string }[];
  stack: { step: number; name: string; detail: string }[];
};

export default function Modules() {
  const [data, setData] = useState<Catalogue | null>(null);

  useEffect(() => {
    api<Catalogue>("/api/v1/intelligence/modules").then(setData).catch(() => setData(null));
  }, []);

  if (!data) return <div className="page"><p className="loading">Loading modules…</p></div>;

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">Fourteen modules, one picture of the shopper</p>
        <h1 className="u-display">Modules</h1>
        <p className="u-lede">
          Each module reads a different slice of the data and produces a specific business
          output. Together they answer five questions.
        </p>
      </header>

      {Object.entries(data.by_question).map(([question, modules]) => (
        <section className="section" key={question}>
          <div className="section__head">
            <h2 className="section__title">{question}</h2>
            <span className="u-eyebrow u-eyebrow--muted">{modules.length} modules</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Module</th>
                  <th>What it analyses</th>
                  <th>Business output</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {modules.map((m) => (
                  <tr key={m.key}>
                    <td>{m.title}</td>
                    <td>{m.reads}</td>
                    <td>{m.business_output}</td>
                    <td><Link href={`/modules/${m.key}`}>Run →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      <section className="band">
        <div>
          <p className="u-eyebrow">The ShopperMind product stack</p>
          <div className="grid-3" style={{ marginTop: "var(--s-5)" }}>
            {data.stack.map((s) => (
              <div key={s.step} className="liquid-card" style={{ padding: "var(--s-4)" }}>
                <p className="u-eyebrow">{String(s.step).padStart(2, "0")}</p>
                <h3 className="section__title" style={{ margin: "var(--s-2) 0" }}>
                  {s.name}
                </h3>
                <p>{s.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="section__head">
          <h2 className="section__title">Segments that move with the customer</h2>
          <Link href="/customers" className="u-mono">See who is in each →</Link>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Segment</th><th>Who they are</th><th>Respond with</th></tr>
            </thead>
            <tbody>
              {data.segments.map((s) => (
                <tr key={s.key}>
                  <td>{s.label}</td><td>{s.who}</td><td>{s.respond_with}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginTop: "var(--s-3)" }}>
          A customer is not assigned to a segment permanently; they move as their behaviour
          changes, and the recommended response moves with them.
        </p>
      </section>
    </div>
  );
}
