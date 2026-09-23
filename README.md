# ShopperMind AI

**Understand. Predict. Personalise. Act.**

An always-on AI shopper intelligence platform for quick service restaurants and retail.
It turns customer data into business decisions, in plain language.

> From “Why did sales fall?” to “What should we do next?”

Most analytics platforms report what happened. A marketing head still has to work out the
cause, then decide what to do about it. ShopperMind is built to do both, and to record
whether the action worked:

```
Data → Insight → Reason → Action → Measurement
       ─────────┘        └──────────────────────
       where most            where ShopperMind
       dashboards stop       continues
```

---

## Run it

Nothing here needs an Azure account or a camera. Every cloud service is optional and the
platform falls back to a local implementation, so the whole product is explorable on a
laptop.

```bash
git clone <this repo> && cd smind
cp .env.example .env          # optional — fill in Azure keys to switch services on
docker compose up --build
```

- Web — http://localhost:3000
- API — http://localhost:8000/docs

Register a workspace at `/register`. Signup seeds a realistic ten-store estate (≈66,000
orders, reviews, campaigns and camera feeds over 75 days), so every module has something
true to find on the first screen.

Without Docker:

```bash
make install     # venv + npm install
make api         # API on :8000 against a local SQLite file
make web         # Next.js on :3000
make test        # 49 tests
```

---

## What it does

### Five questions, fourteen modules

| Question | Modules |
|---|---|
| Who is buying? | customer profiling · store intelligence |
| What are they buying? | purchase behaviour · menu intelligence · basket analysis |
| Why are they buying? | sentiment intelligence · price sensitivity |
| What is stopping them? | voice of customer · competitor intelligence · churn intelligence · **in-store vision** |
| What should we offer them next? | next best offer · campaign intelligence · trend detection |

Thirteen come from the concept doc. **In-store vision** is the fourteenth, added because
the platform now has cameras.

Every module honours one contract: it may not report a number without a reason and at
least one action. This is enforced in code — `Finding.__post_init__` raises if a finding
has no action — not left to discipline.

### The camera layer

Footfall comes from cameras, orders from the POS. Together they give **conversion**, which
neither source can produce alone. When a store is down, that tells you whether fewer people
came in, or the same people came in and left without buying.

The demo estate shows it working:

```
Koramangala converts 24.2% of footfall against a network 40.8%.

  Cameras counted 10,634 visits at this store and the POS recorded 2,576 orders. People
  are walking in and leaving without buying. Average wait at this store is 380 seconds
  against a network 127 — the queue is the most likely cause. This is the one number
  neither the POS nor the camera can produce alone.

  → Re-staff the counter across the store's two busiest hours and re-read conversion
    after a week. (~₹415,832 if conversion reaches the network average)
```

Verbatim output from the seeded workspace. The seed is randomised per tenant, so your
figures will differ — the shape of the finding will not.

**Privacy is structural, not a policy.** The edge agent analyses frames in the store and
transmits only aggregate counts — entries, dwell seconds, queue length, anonymous age
bands. There is no face template, no re-identification, and no join back to the customer
record. The question "who was this person" cannot be answered from what the platform
stores.

Run a store gateway with no hardware:

```bash
cd edge/camera-agent
python agent.py --simulate --cameras KOR-ENT:entrance,KOR-QUE:queue --key <ingest-key>
```

Or against a real stream: `--source rtsp://… --detector azure`.

### Voice

Speech in and out through Azure AI Speech, with the browser's Web Speech API as a fallback
so the microphone works before Azure is configured. English plus six Indian languages.

A spoken answer is written for the ear, not the screen: one number, one reason, one action,
under sixty words, with figures rounded to be heard — "four point three lakh", not
"432,450". The detail stays on screen.

### Shopper Simulator

Test the decision before you make it. Price changes, new items, bundles, promotions and
delistings are estimated from the tenant's own history — demand, basket, margin, segment
and store-level impact — and every result carries its assumptions and its confidence.

It also refuses to flatter you:

```
Chicken Burger does not show a strong enough association in this period to model as a
bundle. The strongest observed pairing is modelled instead, so this answers a different
question than the one asked.
```

### The loop closes

Insights move through `new → acknowledged → actioned → measured`. Recording what actually
happened feeds the **hit rate** on the Insights page — the platform scoring its own
accuracy rather than asking to be taken on trust.

---

## Architecture

```
┌── Next.js 15 (App Router, TypeScript) ──────────── Azure Container Apps ──┐
│   command center · ask (text + voice) · modules · simulator · vision      │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ JWT, tenant-scoped
┌──────────────────────────────▼────────────── FastAPI ─────────────────────┐
│  copilot  →  14 intelligence modules  →  shared pandas Dataset            │
│  simulator                                                                 │
└──────┬─────────────────┬──────────────┬───────────────┬───────────────────┘
       │                 │              │               │
  PostgreSQL         Azure OpenAI   Azure AI        Blob Storage
  Flexible Server    (copilot)      Speech/Vision/  (exports, frames)
                                    Language
       ▲
       │ anonymous aggregate events only
┌──────┴──────────────── edge agent (in store) ────────────────────────────┐
│  RTSP / video → OpenCV HOG or Azure AI Vision → counts → POST /events    │
└──────────────────────────────────────────────────────────────────────────┘
```

Full detail in [docs/01-architecture.md](docs/01-architecture.md).

### Multi-tenancy

Anyone can register; each signup gets an isolated tenant. Every business table carries
`tenant_id`, and reads go through `tenant_query()` rather than a bare `select()`. The JWT
carries the tenant, so a request cannot address another one. `test_tenant_isolation`
asserts an empty tenant sees nothing from a populated one.

### Vertical-neutral

QSR ships first, but the data model is not QSR-specific: `Product` is a menu item or a
SKU, `Store` is an outlet or a branch. Retail, grocery, pharmacy, café and fashion
verticals onboard without a migration — the vertical changes labels and a few module
defaults, not the schema.

---

## Deploy to Azure

```bash
export POSTGRES_ADMIN_PASSWORD='…'
./scripts/deploy-azure.sh prod centralindia
```

Provisions Container Apps (API + web), Postgres Flexible Server, Blob Storage, Key Vault,
Container Registry, Log Analytics and Application Insights, plus Azure OpenAI and a
multi-service AI account. Managed identity throughout — no admin credentials in the
template.

For a cheap evaluation, `deployAiServices=false` skips every AI resource. The platform
still runs, on its local fallbacks.

See [docs/02-azure-deployment.md](docs/02-azure-deployment.md) for sizing, cost and the
production hardening checklist.

---

## Repository

```
apps/api/               FastAPI — the intelligence platform
  app/intelligence/     the fourteen modules, the shared Dataset, the registry
  app/copilot/          tool-calling orchestrator + the local reasoner
  app/simulator/        the what-if engine
  app/services/         Azure OpenAI, Speech, Vision, Language — each with a fallback
  app/seed/             the demo estate
  tests/                49 tests
apps/web/               Next.js — RLAI theme, shared with SupplyMind
edge/camera-agent/      the in-store gateway
infra/main.bicep        the whole Azure estate
docs/                   architecture, deployment, data model, modules, camera & voice
```

---

## Where this is a prototype, not a product

Stated plainly so nothing here is oversold:

- **Correlation, not causation.** Modules say "appears associated with". Nothing here runs
  a controlled experiment, so no finding is proof of cause.
- **The simulator is an estimate.** It extrapolates from historical elasticity and says so,
  caps implausible values, and shows its assumptions. A large price move sits outside the
  observed range and is flagged as indicative only.
- **Competitor intelligence needs a source.** The connector is defined; scraping or a
  licensed review feed is not built.
- **Camera accuracy depends on the detector.** OpenCV HOG runs anywhere and is adequate for
  counting; a production estate should use Azure AI Vision or an on-device model.
- **No experiment framework yet.** Holdout groups are recommended in the copy but not
  enforced by the platform.
- **Postgres RLS is documented, not enabled.** Isolation is enforced in the repository
  layer today; RLS belongs in the production hardening pass.

---

## Interface

The theme is shared with **RLAI SupplyMind** so the two products read as one suite: dark by
default with a light toggle, Inter, a slate surface with a red accent, glass cards and a
collapsible sidebar. The choice persists in `localStorage` and is applied by an inline
script before first paint, so the page never flashes the wrong theme.

Chart palettes come from `apps/web/lib/viz.ts`, copied verbatim from SupplyMind. Dark and
light are separate validated sets rather than one being an inversion of the other — both
pass the categorical checks against their own surface. The light set carries a contrast
warning on three steps, which obliges relief rather than forbidding them: every chart has
visible axis labels and a hover readout, and every module page renders the underlying table
beneath the chart, so a value is never carried by the fill alone.

The RLAI lockup (`apps/web/public/rlailogo.png`, copied from SupplyMind) sits in the
sidebar, the marketing nav and both auth pages, and the favicon is generated from it. The
asset has its navy background baked in rather than being transparent, so it renders as a
solid block on the light sidebar — the same treatment it gets in SupplyMind.

Built by RLAI. ShopperMind and SupplyMind share one theme and one chart palette, so a
customer running both sees one suite rather than two products.
