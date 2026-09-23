# Data model

Vertical-neutral by design. `Product` is a menu item in QSR and a SKU in retail; `Store` is
an outlet or a branch. Adding a vertical changes labels and a few module defaults, not the
schema.

## Control plane

| Table | Purpose |
|---|---|
| `tenants` | One workspace. Carries vertical, currency, timezone, plan, feature switches. |
| `users` | Members of one tenant. Unique on `(tenant_id, email)`, so the same person can belong to several workspaces. |
| `api_keys` | Machine callers — edge agents, POS connectors. Hashed, scoped, never a user token. |

Plan limits (`PLANS` in `models/tenant.py`) are set above what signup seeds. A trial that
ships ten demo stores and then refuses the eleventh camera reads as a bug, not a limit.

## Commerce

| Table | Notes |
|---|---|
| `stores` | Unique on `(tenant_id, code)`. Format drives store-intelligence comparisons. |
| `products` | Unique on `(tenant_id, sku)`. `cost` is what makes margin analysis possible. |
| `customers` | Contact fields are hashed. Denormalised RFM facts refreshed by the profiling module. |
| `orders` | Unique on `(tenant_id, external_id)` — this is what makes ingest idempotent. |
| `order_items` | Line level. Carries `unit_price` separately from the product price, so elasticity can be estimated from realised prices. |

**Why orders carry `daypart`.** Computed at ingest rather than derived per query. Daypart
appears in most purchase-behaviour questions and computing it fourteen times per analysis
run is waste.

**Anonymous orders are expected.** Roughly half of quick-service transactions are never
tied to a known customer — no app, no loyalty scan, cash at the counter. `customer_id` is
nullable and the seeder leaves ~48% of orders unattributed. Modelling every order as
identified would make every retention number flattering and wrong.

## Signals

| Table | Notes |
|---|---|
| `feedback` | One utterance from any listening channel. Enriched once at ingest: PII redacted, sentiment scored, themes tagged. |
| `campaigns` | Offers against response. `redemption_rate` and `roi` are properties, not stored. |
| `competitor_signals` | Public digital signals — reviews, offers, price moves, menu changes. |

**Enrichment happens at ingest, not at read.** Every reading module works off the same
interpretation of the same text, and a module that reads feedback never calls a language
model. That is both a cost decision and a consistency one.

## Vision

| Table | Notes |
|---|---|
| `cameras` | Per-camera privacy posture: `blur_faces`, `retain_frames`, `retention_hours`. `stream_url` is an edge-agent secret and is never returned to the browser. |
| `camera_events` | One aggregated window. Counts, dwell, queue, anonymous demographic bands. |
| `camera_alerts` | Raised on the window that breached, deduplicated to one per camera per type per hour. |

**What is deliberately absent.** No face embeddings, no person ids, no track ids, no join
key from `camera_events` to `customers`. Re-identification is not switched off — it is
absent from the schema, so it cannot be turned on by a configuration change. That is the
difference between a privacy policy and a privacy property.

`demographics` is a JSON count of age bands per window, derived and discarded per frame.
It supports "who comes in at 7pm" without supporting "who was this person".

## Intelligence outputs

| Table | Notes |
|---|---|
| `insights` | The doc's chain as one row: `headline` / `reasoning` / `actions` / `outcome_*`. |
| `segment_assignments` | Rewritten each profiling run. `previous_segment_key` is retained because segment *movement* is itself an insight. |
| `churn_scores` | Probability, band, driver, revenue at risk. |
| `next_best_offers` | Customer → context → intent → recommendation → action. |
| `simulation_runs` | What-if runs, with `was_executed` so a simulation can later be scored against what actually happened. |
| `conversations` / `messages` | Copilot history. `modules_used` and `evidence` are the audit trail for every figure stated. |

**`insights.outcome_delta_pct` is the point.** It is what makes the Learn step real rather
than aspirational — without it, "measurement" is a diagram box. The hit rate on the
Insights page is computed from it.

## Isolation

Every business table has `tenant_id` with an index and `ON DELETE CASCADE`. Reads use
`tenant_query()`, which raises if the model is not tenant-scoped.

Row-level security is the intended second layer and is not yet enabled:

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON orders
  USING (tenant_id = current_setting('app.tenant_id', true));
```

With `SET app.tenant_id` per connection, a missed filter in application code stops being a
data leak. Until then, isolation depends on the repository layer being used consistently —
which `test_tenant_isolation` checks, but only for the paths it covers.

## Indexing

Composite indexes follow the access pattern rather than the column list:

- `(tenant_id, placed_at)` and `(tenant_id, store_id, placed_at)` on orders
- `(tenant_id, captured_at)` on feedback
- `(tenant_id, window_start)` and `(tenant_id, camera_id, window_start)` on camera events
- `(tenant_id, last_order_at)` on customers — the churn scan

Every analytical query starts with a tenant and a period, so `tenant_id` leads every index.
