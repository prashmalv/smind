"use client";

import { useEffect, useState } from "react";

import { api, count, getTenant } from "@/lib/api";

type Settings = {
  tenant: {
    name: string; slug: string; vertical: string; country: string; currency: string;
    timezone: string; plan: string; limits: Record<string, number | string>;
    camera_enabled: boolean; voice_enabled: boolean; trial_ends_at: string | null;
  };
  usage: Record<string, number>;
  platform: Record<string, boolean | string>;
};

export default function SettingsPage() {
  const [data, setData] = useState<Settings | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    api<Settings>("/api/v1/workspace/settings").then(setData).catch(() => setData(null));
  }, []);

  async function toggle(field: "camera_enabled" | "voice_enabled", value: boolean) {
    await api("/api/v1/workspace/settings", { method: "PATCH", body: { [field]: value } });
    setData((d) => (d ? { ...d, tenant: { ...d.tenant, [field]: value } } : d));
    setNote("Saved.");
  }

  if (!data) return <div className="page"><p className="loading">Loading settings…</p></div>;

  const t = data.tenant;
  const services: [string, string, string][] = [
    ["azure_openai", "Azure OpenAI", "Copilot reasoning. Without it the local reasoner answers from the same module output — grounded, just less fluent."],
    ["azure_speech", "Azure AI Speech", "Voice in and out. Without it the browser's own speech engine is used."],
    ["azure_vision", "Azure AI Vision", "Cloud frame analysis. The edge agent can also run detection locally in the store."],
    ["azure_language", "Azure AI Language", "Sentiment and key phrases. Without it a tuned local classifier runs at ingest."],
  ];

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">Workspace</p>
        <h1 className="u-display">Settings</h1>
        <p className="u-lede">{t.name} · {t.vertical} · {t.country} · {t.currency}</p>
      </header>

      <div className="kpis">
        {Object.entries(data.usage).map(([k, v]) => (
          <div className="kpi" key={k}>
            <p className="u-eyebrow u-eyebrow--muted">{k}</p>
            <p className="u-stat kpi__value">{count(v)}</p>
            <p className="kpi__delta">
              {t.limits[k] !== undefined ? `limit ${t.limits[k]} on ${t.plan}` : t.plan}
            </p>
          </div>
        ))}
      </div>

      <section className="section">
        <div className="section__head">
          <h2 className="section__title">Features</h2>
        </div>
        <div className="filters">
          <button
            className="btn btn--ghost" aria-pressed={t.camera_enabled}
            onClick={() => toggle("camera_enabled", !t.camera_enabled)}
          >
            In-store cameras: {t.camera_enabled ? "on" : "off"}
          </button>
          <button
            className="btn btn--ghost" aria-pressed={t.voice_enabled}
            onClick={() => toggle("voice_enabled", !t.voice_enabled)}
          >
            Voice: {t.voice_enabled ? "on" : "off"}
          </button>
        </div>
        {note && <p className="hint">{note}</p>}
      </section>

      <section className="section">
        <div className="section__head">
          <h2 className="section__title">Platform services</h2>
          <span className="u-eyebrow u-eyebrow--muted">
            environment: {String(data.platform.environment)}
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Service</th><th>Status</th><th>What it changes</th></tr>
            </thead>
            <tbody>
              {services.map(([key, label, detail]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td>
                    <span
                      className={`status-dot status-dot--${data.platform[key] ? "ok" : "idle"}`}
                      aria-hidden
                    />
                    {data.platform[key] ? "Configured" : "Fallback in use"}
                  </td>
                  <td>{detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginTop: "var(--s-3)" }}>
          Every Azure service is optional. The platform runs without any of them so it can
          be evaluated before a subscription exists — each one improves a capability rather
          than enabling it.
        </p>
      </section>
    </div>
  );
}
