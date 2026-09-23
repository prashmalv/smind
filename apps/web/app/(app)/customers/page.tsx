"use client";

/**
 * Customers and offers in one place. The three derived tables — segment, churn score and
 * next best offer — are joined here rather than split across three screens, because the
 * person exporting this list needs all three to act on a single row.
 */

import { useCallback, useEffect, useState } from "react";

import { DataTable } from "@/components/DataTable";
import { api, count, getTenant, money, percent } from "@/lib/api";

type Customer = {
  id: string; external_id: string; city: string; order_count: number;
  lifetime_value: number; avg_basket_value: number; last_order_at: string | null;
  segment: string | null; segment_key: string | null; segment_moved_from: string | null;
  segment_rationale: string | null; churn_probability: number | null;
  risk_band: string | null; churn_driver: string | null; revenue_at_risk: number | null;
  next_best_offer: string | null; offer_type: string | null;
  offer_propensity: number | null; inferred_intent: string | null;
};
type SegmentBreakdown = {
  total_customers: number;
  segments: {
    key: string; label: string; customers: number; share_pct: number;
    arrived_from: { segment: string; customers: number }[];
  }[];
  movement_note: string;
};
type Offer = {
  id: string; offer_type: string; offer_text: string; context: string;
  inferred_intent: string; propensity: number; expected_uplift: number; status: string;
};

export default function Customers() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [segments, setSegments] = useState<SegmentBreakdown | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [segmentFilter, setSegmentFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const currency = getTenant()?.currency ?? "INR";

  const load = useCallback(async () => {
    const qs = new URLSearchParams();
    if (segmentFilter) qs.set("segment", segmentFilter);
    if (riskFilter) qs.set("risk_band", riskFilter);
    const [c, o] = await Promise.all([
      api<Customer[]>(`/api/v1/workspace/customers?${qs}`),
      api<Offer[]>("/api/v1/workspace/offers"),
    ]);
    setCustomers(c);
    setOffers(o);
    try {
      setSegments(await api<SegmentBreakdown>("/api/v1/workspace/segments"));
      setNeedsRefresh(false);
    } catch {
      setSegments(null);
      setNeedsRefresh(true);
    }
  }, [segmentFilter, riskFilter]);

  useEffect(() => { load().catch(() => setCustomers([])); }, [load]);

  async function refresh() {
    setNote("Running all modules and rewriting segments, churn scores and offers…");
    await api("/api/v1/intelligence/refresh", { method: "POST", body: { period_days: 30 } });
    setNote(null);
    await load();
  }

  async function pushOffers() {
    const ids = offers.filter((o) => o.status === "pending").slice(0, 50).map((o) => o.id);
    if (!ids.length) return;
    const res = await api<{ pushed: number; note: string }>("/api/v1/workspace/offers/push", {
      method: "POST", body: { offer_ids: ids },
    });
    setNote(`${res.pushed} offers marked as pushed. ${res.note}`);
    await load();
  }

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">Customer → context → intent → recommendation → action</p>
        <h1 className="u-display">Customers &amp; offers</h1>
        <p className="u-lede">
          A record that a customer bought something is history. This screen carries what
          they are likely to do next, and what to put in front of them.
        </p>
      </header>

      {needsRefresh && (
        <div className="empty" style={{ marginBottom: "var(--s-5)" }}>
          <p>
            Segments have not been assigned yet. Run the intelligence refresh to score
            every customer and generate offers.
          </p>
          <button className="btn" style={{ marginTop: "var(--s-3)" }} onClick={refresh}>
            Refresh intelligence
          </button>
        </div>
      )}
      {note && <p className="hint" style={{ marginBottom: "var(--s-4)" }}>{note}</p>}

      {segments && (
        <section className="section" style={{ marginTop: 0 }}>
          <div className="section__head">
            <h2 className="section__title">Segments</h2>
            <span className="u-eyebrow u-eyebrow--muted">
              {count(segments.total_customers)} customers scored
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Segment</th><th className="num">Customers</th>
                  <th className="num">Share</th><th>Arrived from</th><th />
                </tr>
              </thead>
              <tbody>
                {segments.segments.map((s) => (
                  <tr key={s.key}>
                    <td>{s.label}</td>
                    <td className="num">{count(s.customers)}</td>
                    <td className="num">{percent(s.share_pct)}</td>
                    <td>
                      {s.arrived_from.length
                        ? s.arrived_from.slice(0, 2)
                            .map((a) => `${a.customers} from ${a.segment}`).join("; ")
                        : "—"}
                    </td>
                    <td>
                      <button
                        className="btn btn--ghost btn--sm"
                        onClick={() => setSegmentFilter(segmentFilter === s.key ? "" : s.key)}
                        aria-pressed={segmentFilter === s.key}
                      >
                        {segmentFilter === s.key ? "Clear" : "Filter"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint" style={{ marginTop: "var(--s-3)" }}>{segments.movement_note}</p>
        </section>
      )}

      <section className="section">
        <div className="section__head">
          <h2 className="section__title">Customers</h2>
          <button className="btn btn--ghost btn--sm" onClick={refresh}>Re-score</button>
        </div>
        <div className="filters">
          <span className="u-eyebrow u-eyebrow--muted">Churn risk</span>
          {["", "high", "medium", "low"].map((r) => (
            <button
              key={r || "all"} className="btn btn--ghost btn--sm"
              aria-pressed={riskFilter === r} onClick={() => setRiskFilter(r)}
            >
              {r || "All"}
            </button>
          ))}
        </div>
        <DataTable
          columns={[
            { key: "external_id", label: "Customer", format: "text" },
            { key: "segment", label: "Segment", format: "text" },
            { key: "order_count", label: "Orders", format: "number" },
            { key: "lifetime_value", label: "Lifetime value", format: "currency" },
            { key: "risk_band", label: "Churn risk", format: "text" },
            { key: "churn_driver", label: "Why", format: "text" },
            { key: "next_best_offer", label: "Next best offer", format: "text" },
          ]}
          rows={customers as unknown as Record<string, unknown>[]}
          currency={currency}
          empty="No customers match this filter."
        />
      </section>

      <section className="section">
        <div className="section__head">
          <h2 className="section__title">Offers ready to push</h2>
          <button className="btn btn--sm" onClick={pushOffers} disabled={!offers.length}>
            Push the top 50 to CRM
          </button>
        </div>
        <DataTable
          columns={[
            { key: "offer_text", label: "Offer", format: "text" },
            { key: "offer_type", label: "Type", format: "text" },
            { key: "context", label: "Context", format: "text" },
            { key: "inferred_intent", label: "Inferred intent", format: "text" },
            { key: "propensity", label: "Propensity", format: "decimal" },
            { key: "expected_uplift", label: "Expected uplift", format: "currency" },
            { key: "status", label: "Status", format: "text" },
          ]}
          rows={offers as unknown as Record<string, unknown>[]}
          currency={currency}
          empty="No offers generated yet. Run the intelligence refresh."
        />
        <p className="hint" style={{ marginTop: "var(--s-3)" }}>
          ShopperMind decides what to offer; your CRM delivers it. Report redemptions back
          through the orders feed so the loop closes and the propensity model improves.
        </p>
      </section>
    </div>
  );
}
