"use client";

/**
 * In-store vision. The live view is operational — it answers "what is happening right
 * now" — while the reasoning about footfall and conversion lives in the store_vision
 * and store_intelligence modules.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataTable } from "@/components/DataTable";
import { api, count, relativeTime, seconds } from "@/lib/api";

// Metrics a zone does not measure come back null, so the table can show "—" rather
// than a zero that reads as a measurement.
type Feed = {
  camera_id: string; camera_name: string; camera_code: string; store_name: string;
  zone_type: string; mode: string;
  footfall: number | null; avg_queue_length: number | null;
  max_queue_length: number | null; avg_wait_seconds: number | null;
  abandonments: number | null; avg_dwell_seconds: number | null;
  last_window: string | null; healthy: boolean;
};
type Live = {
  window_minutes: number; cameras_total: number; cameras_reporting: number;
  cameras_stale: number; total_footfall: number;
  cameras_offline: { camera_name: string; store_name: string; last_seen_at: string | null }[];
  feeds: Feed[];
};
type Alert = {
  id: string; alert_type: string; severity: string; message: string;
  store_name: string; observed_value: number; threshold_value: number; raised_at: string;
};
type Camera = {
  id: string; code: string; name: string; store_name: string; zone_type: string;
  mode: string; healthy: boolean; last_seen_at: string | null;
  blur_faces: boolean; retain_frames: boolean; stream_configured: boolean;
};

export default function Cameras() {
  const [live, setLive] = useState<Live | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [minutes, setMinutes] = useState(1440);
  const [key, setKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [l, a, c] = await Promise.all([
      api<Live>(`/api/v1/cameras/live?minutes=${minutes}`),
      api<Alert[]>("/api/v1/cameras/alerts"),
      api<Camera[]>("/api/v1/cameras"),
    ]);
    setLive(l); setAlerts(a); setCameras(c);
  }, [minutes]);

  useEffect(() => { load().catch(() => setLive(null)); }, [load]);

  async function mintKey() {
    const res = await api<{ key: string }>("/api/v1/cameras/keys", {
      method: "POST", body: { label: "Edge agent" },
    });
    setKey(res.key);
  }

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">In-store vision</p>
        <h1 className="u-display">What the cameras see</h1>
        <p className="u-lede">
          Footfall, queue length and dwell time as anonymous aggregates. No face
          templates, no identity, and no join back to the customer record — the platform
          is built so that &ldquo;who was this person&rdquo; cannot be answered from what
          it stores.
        </p>
      </header>

      <div className="filters">
        <span className="u-eyebrow u-eyebrow--muted">Window</span>
        {[60, 360, 1440].map((m) => (
          <button
            key={m} className="btn btn--ghost btn--sm" aria-pressed={minutes === m}
            onClick={() => setMinutes(m)}
          >
            {m === 60 ? "Last hour" : m === 360 ? "Last 6 hours" : "Last 24 hours"}
          </button>
        ))}
        <button className="btn btn--ghost btn--sm" onClick={() => load()}>Refresh</button>
        <Link href="/modules/store_vision" className="u-mono" style={{ marginLeft: "auto" }}>
          Full vision analysis →
        </Link>
      </div>

      {!live && <p className="loading">Loading camera state…</p>}

      {live && (
        <>
          <div className="kpis">
            <div className="kpi">
              <p className="u-eyebrow u-eyebrow--muted">Cameras reporting</p>
              <p className="u-stat kpi__value">
                {live.cameras_reporting}/{live.cameras_total}
              </p>
              <p className={`kpi__delta${live.cameras_stale > 0 ? " kpi__delta--bad" : ""}`}>
                {live.cameras_stale > 0
                  ? `${live.cameras_stale} silent for over 15 min`
                  : "all reporting now"}
              </p>
            </div>
            <div className="kpi">
              <p className="u-eyebrow u-eyebrow--muted">Footfall in window</p>
              <p className="u-stat kpi__value">{count(live.total_footfall)}</p>
              <p className="kpi__delta">entrance and drive-thru zones</p>
            </div>
            <div className="kpi">
              <p className="u-eyebrow u-eyebrow--muted">Longest queue</p>
              <p className="u-stat kpi__value">
                {live.feeds[0]?.max_queue_length ?? "—"}
              </p>
              <p className="kpi__delta">
                {live.feeds[0]?.max_queue_length != null
                  ? live.feeds[0].store_name
                  : "no queue zones reporting"}
              </p>
            </div>
            <div className="kpi">
              <p className="u-eyebrow u-eyebrow--muted">Open alerts</p>
              <p className="u-stat kpi__value">{alerts.length}</p>
              <p className="kpi__delta">
                {alerts.filter((a) => a.severity === "high").length} high severity
              </p>
            </div>
          </div>

          {alerts.length > 0 && (
            <section className="section">
              <div className="section__head">
                <h2 className="section__title">Alerts</h2>
                <span className="u-eyebrow u-eyebrow--muted">
                  raised on the window that breached
                </span>
              </div>
              {alerts.slice(0, 8).map((a) => (
                <div className="finding" key={a.id} style={{ paddingBottom: "var(--s-4)" }}>
                  <div className="finding__meta">
                    <span className={`sev sev--${a.severity}`}>{a.severity}</span>
                    <span className="u-eyebrow u-eyebrow--muted">
                      {a.alert_type.replace(/_/g, " ")}
                    </span>
                    <span className="u-mono" style={{ color: "var(--ink-3)" }}>
                      {relativeTime(a.raised_at)}
                    </span>
                  </div>
                  <p style={{ color: "var(--ink)", marginTop: "var(--s-2)" }}>
                    {a.message} — {a.observed_value.toFixed(0)} against a threshold of{" "}
                    {a.threshold_value.toFixed(0)}.
                  </p>
                  <button
                    className="btn btn--ghost btn--sm"
                    style={{ marginTop: "var(--s-3)" }}
                    onClick={async () => {
                      await api(`/api/v1/cameras/alerts/${a.id}/resolve`, { method: "PATCH" });
                      load();
                    }}
                  >
                    Resolve
                  </button>
                </div>
              ))}
            </section>
          )}

          <section className="section">
            <div className="section__head">
              <h2 className="section__title">Live feeds</h2>
              <span className="u-eyebrow u-eyebrow--muted">
                aggregated windows, not video
              </span>
            </div>
            <DataTable
              columns={[
                { key: "camera_name", label: "Camera", format: "text" },
                { key: "store_name", label: "Store", format: "text" },
                { key: "zone_type", label: "Zone", format: "text" },
                { key: "footfall", label: "Footfall", format: "number" },
                { key: "avg_queue_length", label: "Avg queue", format: "decimal" },
                { key: "max_queue_length", label: "Peak queue", format: "number" },
                { key: "avg_wait_seconds", label: "Avg wait (s)", format: "number" },
                { key: "abandonments", label: "Left queue", format: "number" },
              ]}
              rows={live.feeds}
              empty="No camera events in this window. Run the edge agent, or check that a camera is registered."
            />
          </section>

          <section className="section">
            <div className="section__head">
              <h2 className="section__title">Registered cameras</h2>
              <button className="btn btn--ghost btn--sm" onClick={mintKey}>
                Create an ingest key
              </button>
            </div>

            {key && (
              <div className="empty" style={{ marginBottom: "var(--s-4)" }}>
                <p className="u-eyebrow">Ingest key — shown once</p>
                <p className="u-mono" style={{ wordBreak: "break-all", marginTop: "var(--s-2)", color: "var(--ink)" }}>
                  {key}
                </p>
                <p className="hint">
                  Give this to the edge agent as <code>CAMERA_AGENT_KEY</code>. It is not
                  retrievable again.
                </p>
              </div>
            )}

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Camera</th><th>Store</th><th>Zone</th><th>Mode</th>
                    <th>Privacy</th><th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {cameras.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <span
                          className={`status-dot status-dot--${c.healthy ? "ok" : "bad"}`}
                          aria-hidden
                        />
                        {c.name}
                      </td>
                      <td>{c.store_name}</td>
                      <td>{c.zone_type}</td>
                      <td>{c.mode}</td>
                      <td>
                        {c.blur_faces ? "faces blurred" : "no blur"}
                        {c.retain_frames ? " · frames retained" : " · no frames stored"}
                      </td>
                      <td>{relativeTime(c.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {cameras.length === 0 && (
              <p className="hint">
                No cameras registered. Add one through the API, then point the edge agent at
                it — it can run against a sample video file with no hardware.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
