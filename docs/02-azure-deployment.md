# Azure deployment

## Deploy

```bash
az login
export POSTGRES_ADMIN_PASSWORD='<a strong password>'
./scripts/deploy-azure.sh prod centralindia
```

The script creates the resource group, deploys `infra/main.bicep`, builds all three images
in ACR, then redeploys with the real image tags. First run takes 10–15 minutes, mostly
Postgres provisioning. Re-running is idempotent and rolls out new image tags.

**There is no cache tier.** Azure Cache for Redis is retiring, and nothing in the platform
read from it — the module results are fast enough from Postgres and pandas that a cache
would have been paying for a layer no code touched. If module runs later become the
bottleneck, add Azure Managed Redis then, against a measured need.

## What gets created

| Resource | SKU (dev → prod) | Why |
|---|---|---|
| Container Apps environment | — | Scale-to-low, no cluster to operate |
| API container app | 1 CPU/2 GiB → 2 CPU/4 GiB, 1–3 → 2–10 replicas | pandas work is CPU-bound |
| Web container app | 0.5 CPU/1 GiB | Next.js standalone server |
| Postgres Flexible Server | B2ms Burstable → D4ds_v5 General Purpose | See the note below |
| Blob Storage | LRS → ZRS | Exports, and frames where a tenant opts in |
| Key Vault | Standard, RBAC | Secrets, referenced by managed identity |
| Container Registry | Basic → Premium | Images |
| Azure OpenAI | S0, `gpt-4o` + `text-embedding-3-large` | Copilot reasoning |
| Azure AI Services (multi) | S0 | Speech, Vision and Language on one key |
| Log Analytics + App Insights | PerGB2018, 30-day retention | Traces and container logs |

**Postgres tier.** Burstable is right for dev and staging: the analytical load is bursty
and short, which is exactly what CPU credits are for. Production moves to General Purpose
because a nightly refresh across fourteen modules should not be competing for credits at
the moment someone opens a dashboard.

**Azure OpenAI region.** Defaults to `swedencentral` rather than the resource-group region,
because `gpt-4o` capacity is not available everywhere. Data residency requirements may
override this — check availability in your required region before assuming Central India
will take the deployment.

**Skipping the AI services.** `-p deployAiServices=false` omits Azure OpenAI and the
multi-service account entirely. The platform still runs on its local reasoner, the
browser's speech engine, and local sentiment. Useful for a cheap evaluation environment.

## Indicative monthly cost

Rough order of magnitude for a mid-size estate (20 stores, 50 cameras, 25 seats), Central
India list prices, USD. Treat as a planning figure, not a quote — verify with the Azure
pricing calculator for your region and commitment.

| Component | Dev | Production |
|---|---|---|
| Container Apps | ~$30 | ~$180 |
| Postgres Flexible Server | ~$45 | ~$420 |
| Storage + registry + logs | ~$25 | ~$90 |
| Azure OpenAI (usage) | ~$40 | ~$300–900 |
| Speech / Vision / Language | ~$20 | ~$150 |
| **Total** | **~$160** | **~$1,150–1,750** |

The OpenAI line dominates the variance and is the one worth controlling. Three levers:

1. The copilot's tool budget is capped at three rounds per question.
2. Sentiment and theme enrichment happen once at ingest, not per request — so a module
   reading feedback never calls a model.
3. The local reasoner answers without any model call at all. On a plan where the copilot
   is not included, the product still works.

## Production hardening

The template deploys a working platform, not a hardened one. Before real customer data:

- [ ] **Private networking.** Postgres currently allows Azure services with an
      open firewall rule so an evaluation deployment works out of the box. Move it behind
      a VNet with private endpoints and delete `AllowAllAzureServices`.
- [ ] **Postgres row-level security.** Isolation is enforced in the repository layer today.
      Add RLS policies on `tenant_id` and set `app.tenant_id` per connection, so a missed
      filter in application code cannot leak across tenants.
- [ ] **Rotate the JWT signing key.** It is derived from `uniqueString()` in the template.
      Move it to Key Vault with a rotation policy.
- [ ] **Refresh tokens.** Access tokens currently last twelve hours with no refresh flow
      and no revocation list. Add both.
- [ ] **Rate limiting.** No limits on `/copilot/ask` or `/ingest/*`. Put Azure Front Door or
      APIM in front with per-tenant quotas — the copilot endpoint costs money per call.
- [ ] **WAF and custom domain.** Front Door with a certificate; lock ingress to it.
- [ ] **Alembic migrations.** `Base.metadata.create_all()` on startup is fine for a
      prototype and wrong for production. Generate an initial migration and switch.
- [ ] **Backup restore drill.** Backups are configured (35-day retention, geo-redundant in
      prod). Prove a restore works before relying on it.
- [ ] **Managed identity for Postgres.** The connection string embeds the password. Switch
      to Entra ID authentication with the API's user-assigned identity.
- [ ] **Container scanning.** Enable Defender for Containers on the registry.
- [ ] **Data residency review.** If the OpenAI account sits outside India, confirm the
      prompt payloads crossing regions are acceptable to the customer. The copilot sends
      module output — aggregate figures, not customer records — but that is a decision for
      the customer's DPO, not an assumption to make on their behalf.

## Edge agents

Camera agents run in the stores, not in Azure. Two options:

**Azure IoT Edge** — deploy `edge/camera-agent` as a module. Gives you fleet management,
offline buffering, and staged rollouts across the estate.

**Plain container** — on any store gateway with Docker:

```bash
docker run -d --restart unless-stopped \
  -e SHOPPERMIND_API_URL=https://<your-api>.azurecontainerapps.io \
  -e CAMERA_AGENT_KEY=smk_… \
  <registry>/shoppermind-edge:latest \
  --source rtsp://user:pass@10.0.0.9/stream1 --camera KOR-ENT --zone entrance
```

The agent only needs outbound HTTPS. No inbound port, and no camera stream leaves the
store — the gateway posts counts.

## Operating it

**Nightly refresh.** `POST /api/v1/intelligence/refresh` runs all fourteen modules and
persists findings, segments, churn scores and offers. Schedule it per tenant with a
Container Apps job or Azure Functions timer. It is safe to re-run: same-day findings with
status `new` are replaced rather than duplicated, because an insight is a statement about
a period, not an event.

**Health probes.** `/health` is liveness. `/ready` actually queries the database, so a
replica that cannot reach Postgres never takes traffic.

**What to alert on.** API 5xx rate, `/ready` failures, Postgres CPU and connection count,
Azure OpenAI 429s (capacity, not errors — raise the deployment capacity), and camera
agents going quiet. The last one is the easiest to miss and the most corrosive: a camera
that stops reporting makes conversion silently wrong rather than visibly absent.
