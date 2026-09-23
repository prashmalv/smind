"use client";

/**
 * Data sources. The honest version: it names exactly which modules cannot run yet and
 * what would unblock them, rather than showing every module and letting them fail quietly.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { API_URL, api, count, getToken, relativeTime } from "@/lib/api";

type Source = {
  key: string; label: string; records: number; required: boolean;
  how: string; connected: boolean; last_seen?: string | null;
};
type Status = {
  sources: Source[];
  ready: boolean;
  missing_required: string[];
  modules_blocked: { module_key: string; missing: string[] }[];
};

const UPLOADABLE = ["stores", "products", "customers", "feedback"];

export default function DataSources() {
  const [status, setStatus] = useState<Status | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [entity, setEntity] = useState("products");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setStatus(await api<Status>("/api/v1/ingest/status"));
  }, []);

  useEffect(() => { load().catch(() => setStatus(null)); }, [load]);

  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setNote("Uploading…");
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/api/v1/ingest/csv/${entity}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body: form,
    });
    if (res.ok) {
      const data = await res.json();
      setNote(
        `${data.created} ${entity} created from ${data.rows_in_file} rows.`
        + (data.errors?.length ? ` ${data.errors.length} rows had problems.` : ""),
      );
      await load();
    } else {
      setNote("The upload failed. Check the file has a header row matching the expected columns.");
    }
  }

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">It sits on top of the systems you already have</p>
        <h1 className="u-display">Data sources</h1>
        <p className="u-lede">
          ShopperMind does not replace your POS or CRM. It connects to them, combines what
          they know, and adds an intelligence layer above.
        </p>
      </header>

      {!status && <p className="loading">Checking what is connected…</p>}

      {status && (
        <>
          {!status.ready && (
            <div className="empty" style={{ marginBottom: "var(--s-5)" }}>
              <p className="u-eyebrow">Not ready yet</p>
              <p style={{ marginTop: "var(--s-2)" }}>
                These are required before the core modules can produce anything meaningful:{" "}
                <strong>{status.missing_required.join(", ")}</strong>.
              </p>
            </div>
          )}

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Source</th><th className="num">Records</th><th>Last seen</th>
                  <th>How to connect</th>
                </tr>
              </thead>
              <tbody>
                {status.sources.map((s) => (
                  <tr key={s.key}>
                    <td>
                      <span
                        className={`status-dot status-dot--${s.connected ? "ok" : s.required ? "bad" : "idle"}`}
                        aria-hidden
                      />
                      {s.label}
                      {s.required && !s.connected && (
                        <span className="u-mono" style={{ color: "var(--bad)" }}> required</span>
                      )}
                    </td>
                    <td className="num">{count(s.records)}</td>
                    <td>{s.last_seen ? relativeTime(s.last_seen) : "—"}</td>
                    <td>{s.how}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {status.modules_blocked.length > 0 && (
            <section className="section">
              <div className="section__head">
                <h2 className="section__title">Modules waiting on data</h2>
                <span className="u-eyebrow u-eyebrow--muted">
                  {status.modules_blocked.length} blocked
                </span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Module</th><th>Needs</th><th /></tr>
                  </thead>
                  <tbody>
                    {status.modules_blocked.map((b) => (
                      <tr key={b.module_key}>
                        <td>{b.module_key.replace(/_/g, " ")}</td>
                        <td>{b.missing.join(", ")}</td>
                        <td><Link href={`/modules/${b.module_key}`}>Open →</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="section">
            <div className="section__head">
              <h2 className="section__title">Upload a CSV</h2>
              <span className="u-eyebrow u-eyebrow--muted">
                the day-one path, before any integration
              </span>
            </div>
            <div className="filters">
              {UPLOADABLE.map((e) => (
                <button
                  key={e} className="btn btn--ghost btn--sm"
                  aria-pressed={entity === e} onClick={() => setEntity(e)}
                >
                  {e}
                </button>
              ))}
            </div>
            <div className="composer__row">
              <input ref={fileRef} className="input" type="file" accept=".csv" />
              <button className="btn" onClick={upload}>Upload {entity}</button>
            </div>
            <p className="hint" style={{ marginTop: "var(--s-3)" }}>
              Expected columns —{" "}
              {entity === "stores" && "code, name, city, state, region, format"}
              {entity === "products" && "sku, name, category, subcategory, price, cost, is_combo"}
              {entity === "customers" && "external_id, age_band, gender, city, signup_channel"}
              {entity === "feedback" && "body (or text/review), source, store_code, rating"}
              . Orders go through <code>POST /api/v1/ingest/orders</code> because they are nested.
            </p>
            {note && <p className="hint" style={{ marginTop: "var(--s-2)" }}>{note}</p>}
          </section>

          <section className="section">
            <div className="section__head">
              <h2 className="section__title">Connect a live feed</h2>
            </div>
            <p className="u-measure">
              Point your POS connector at <code>POST /api/v1/ingest/orders</code>. It is
              idempotent on <code>external_id</code>, so a connector that retries a batch
              cannot double-count revenue. Review and social listening go to{" "}
              <code>/ingest/feedback</code>, where every item is PII-redacted and enriched
              once at ingest. The full API reference is at{" "}
              <a href={`${API_URL}/docs`} target="_blank" rel="noreferrer">{API_URL}/docs</a>.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
