# Architecture

## The shape of the thing

ShopperMind is a multi-tenant SaaS with four pieces: a Next.js front end, a FastAPI
intelligence service, a Postgres database, and an edge agent that runs inside each store.
Azure AI services attach to the middle layer and every one of them is optional.

```
                        ┌─────────────────────────────────┐
  browser ──────────────►  Next.js 15 · Container Apps    │
  (mic, speakers)       │  command center / ask / modules │
                        └──────────────┬──────────────────┘
                                       │  JWT: {sub, tid, role}
                        ┌──────────────▼──────────────────┐
                        │  FastAPI · Container Apps       │
                        │                                 │
                        │  copilot ──► tools ──► modules  │
                        │  simulator ─────────► modules   │
                        │  ingest ────────────► Postgres  │
                        └───┬──────────┬─────────┬────────┘
                            │          │         │
              ┌─────────────▼──┐  ┌────▼─────┐  ┌▼────────────┐
              │ Postgres       │  │ Azure AI │  │ Blob Storage │
              │ Flexible Server│  │ OpenAI   │  │              │
              │                │  │ Speech   │  └──────────────┘
              │ tenant_id on   │  │ Vision   │
              │ every table    │  │ Language │
              └────────────────┘  └──────────┘
                            ▲
                            │ POST /cameras/events  (counts only)
              ┌─────────────┴───────────────────────┐
              │  edge agent · in-store gateway      │
              │  RTSP ──► detect ──► aggregate      │
              └─────────────────────────────────────┘
```

## Why these choices

**FastAPI + pandas for the intelligence layer, not SQL views.** The modules do work that
is awkward in SQL — association rules, log-log elasticity regression, RFM banding, term
frequency comparison across periods. Expressing that in pandas keeps each module readable
by the person who has to argue with its output.

**One shared `Dataset` per run, not a query per module.** Fourteen modules over the same
period would otherwise issue fourteen sets of queries. `Dataset` loads each frame once,
lazily, and caches it on the `AnalysisContext`.

**Frames are warmed before the fan-out.** `run_all()` calls `Dataset.warm()` on the
calling thread, then runs the modules in a thread pool. A SQLAlchemy `Session` is not
thread-safe, so every query must happen before the threads start. Without this, a module
that lazily touched an unloaded frame from a worker thread would race the session and
fail — and the registry would swallow it into an empty result, which looks like "no
findings" rather than like a bug. That failure mode is exactly why the warm step is
explicit and the frame list is enumerated rather than discovered.

**Next.js without a component library.** The theme is shared with RLAI SupplyMind, and
matching it exactly — the glass card treatment, the red gradient on the active nav, the
collapsible sidebar, the two validated chart palettes — is easier to do from tokens than by
bending a library's defaults into the same shape. The components are small enough that
owning them costs less than overriding them.

**Theme applied before paint.** An inline script in the root layout reads `sm_theme` and
sets the class synchronously. A React effect runs after the browser has already painted, so
relying on the provider alone would show a flash of the wrong theme on every load. The
provider keeps React in sync and persists the choice; it is not what prevents the flash.

## The module contract

Every module is an `IntelligenceModule` returning a `ModuleResult`:

```python
@dataclass
class Finding:
    headline: str          # 2. Insight   — what happened
    reasoning: str         # 3. Reason    — why it happened
    actions: list[Action]  # 4. Action    — what to do
    ...
    def __post_init__(self):
        if not self.actions:
            raise ValueError("A module must not report a number without a recommendation.")
```

That exception is the product's thesis made mechanical. A module that computes a metric and
stops is a dashboard; the constructor will not let one exist.

`ModuleResult.to_dict()` passes everything through `json_safe()`, which converts NaN and
infinity to `null`. Those turn up honestly — a store with no camera has no conversion rate
— and they are legal floats but illegal JSON. Handling it once at the contract level means
fourteen modules do not each have to defend against it, and a missing number reaches the UI
as `null` so it renders as "no data" instead of zero.

## The copilot

Two paths, one shape of answer.

**With Azure OpenAI** it is a tool-calling loop over `run_module`, `run_modules`,
`simulate` and `get_context`. The model has no direct database access by design — it can
only see what a module returned, so every number it states is traceable to a module and a
period. The tool budget is three rounds; after that it must answer with what it has.

**Without Azure OpenAI** `_compose_locally` routes the question with regex, runs the
matching modules, and assembles the same three movements — what happened, why, what to do
— directly from the findings. It is less fluent and handles follow-ups less gracefully, but
it is grounded in exactly the same numbers. This is what makes the platform demonstrable
before a subscription exists, and it is why the local path is a first-class code path
rather than a stub.

The routing table is ordered by specificity. `"what should we promote"` is matched above
the pricing pattern, because "promote" would otherwise pull a merchandising question into
price sensitivity.

## Multi-tenancy

- Every business table carries `tenant_id` via `TenantMixin`.
- Reads go through `tenant_query(model, tenant_id)`, which raises if the model is not
  tenant-scoped, rather than a bare `select()`.
- The JWT carries `tid`; `Principal.tenant_id` scopes every request. A caller cannot
  address another tenant because the tenant is never a request parameter.
- Roles are ranked (`viewer < analyst < manager < admin < owner`) and `Principal.require()`
  compares ranks rather than matching strings.
- Edge agents authenticate with a hashed API key, not a user token — the caller is a
  gateway in a shop, not a person in a browser.

Postgres row-level security is the next layer and is **not** enabled yet; see the hardening
checklist in `02-azure-deployment.md`.

## Failure behaviour

| Failure | What happens |
|---|---|
| A module raises | `run_module` logs and returns an empty result. One broken module cannot take down a page. |
| Azure OpenAI is down | The copilot falls back to the local reasoner and labels the answer `local reasoner` in the UI. |
| Azure Speech is unavailable | The browser's Web Speech API is used; `/voice/token` returns `mode: browser` rather than an error. |
| Azure AI Language is unavailable | A tuned local sentiment and theme classifier runs at ingest. |
| The store's network drops | The edge agent queues events in memory (capped at 2,000) and posts them with the next batch. Losing an hour's footfall would silently corrupt that day's conversion rate. |
| An unhandled 500 | The handler attaches CORS headers explicitly. Starlette's server-error handling sits outside `CORSMiddleware`, so without this the browser reports a CORS failure and the real error never surfaces. |

## Performance

On the seeded estate (≈66,000 orders, 12,000 customers, 7,560 camera events):

| Operation | Time |
|---|---|
| Full pulse (8 modules) | ~600 ms |
| Single module | 150–400 ms |
| All 14 modules + persist | ~3 s |
| Copilot answer (local reasoner) | ~1.7 s |
| Workspace signup incl. seeding | ~8 s |

The seeder uses `bulk_insert_mappings` with pre-assigned ids. Adding orders through the
ORM and flushing to obtain each id costs a round trip per order, which turned signup into
a thirty-second wait; the bulk path handles five times the data in less time.
