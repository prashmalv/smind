# Cameras and voice

## In-store vision

### The design rule

Frames do not leave the store. The edge agent analyses them on a gateway in the shop and
transmits a row of counts. What arrives at the platform is:

```json
{
  "camera_code": "KOR-QUE",
  "window_start": "2026-09-22T19:00:00Z",
  "window_seconds": 300,
  "avg_queue_length": 6.4,
  "max_queue_length": 11,
  "avg_wait_seconds": 548.6,
  "abandonment_count": 3,
  "demographics": {"18-24": 12, "25-34": 16, "35-44": 9, "45+": 9}
}
```

No image, no face template, no person id, no track id. There is no join key from
`camera_events` to `customers` — not disabled, absent from the schema. Re-identification
cannot be enabled by flipping a setting, because nothing is stored that would support it.

`demographics` is a per-window count of apparent age bands, derived per frame and
discarded. It answers "who comes in at 7pm" without answering "who was this person".

Per-camera controls: `blur_faces` (default on), `retain_frames` (default off),
`retention_hours` (default 0). Where a tenant does opt into retaining frames, the Blob
lifecycle rule in `main.bicep` deletes them after one day — enforced by the platform, not
by the application remembering to.

### Detectors

| Detector | When | Notes |
|---|---|---|
| `--simulate` | Demos, development, CI | Generates a plausible day with lunch and dinner peaks. No hardware, no video file. |
| `local` (OpenCV HOG) | Default on a store gateway | Runs on a cheap box with no GPU. Adequate for counting, which is all the platform needs. |
| `azure` (Azure AI Vision) | Where accuracy matters | Calls the `people` model only — never Face, never identification. |

HOG over a heavier model is a deliberate trade: the platform needs a count, not a
classification, and a store gateway is not a GPU box. Where an estate needs better
accuracy, `--detector azure` is a flag, not a rewrite.

### From frames to numbers

A window collects one observation every two seconds for five minutes, then reduces:

**Entries** are counted as upward transitions, not raw headcount. Someone standing still
for five minutes is one visitor, not 150.

**Wait** comes from Little's Law — time in the system equals number in the system divided
by service rate. Defensible from counts alone, which is exactly why it needs no tracking of
individuals.

**Abandonment** is a drop of two or more from an already long queue.

**Dwell** is total person-seconds divided by throughput.

### Alerts

Raised on the window that breached, not on a daily roll-up — a queue alert that arrives
tomorrow is a report. Deduplicated to one per camera per type per hour, because an alert
that fires every five minutes is noise and gets muted, which is worse than no alert.

Defaults: queue length 6, wait 240s, occupancy 60. Each is a starting point a store manager
should tune to their site's actual capacity.

### Running an agent

```bash
# No hardware
python agent.py --simulate --cameras KOR-ENT:entrance,KOR-QUE:queue --key smk_…

# A video file, looped — a short clip stands in for a day
python agent.py --source samples/store.mp4 --camera KOR-ENT --zone entrance --key smk_…

# A real camera
python agent.py --source rtsp://user:pass@10.0.0.9/stream1 \
                --camera KOR-ENT --zone entrance --detector azure --key smk_…

# Backfill history so a new workspace has something to analyse
python agent.py --backfill-days 30 --cameras KOR-ENT:entrance,KOR-QUE:queue --key smk_…
```

Get the ingest key from **In-store vision → Create an ingest key**. It is shown once.

The agent only needs outbound HTTPS. If the store's network drops it queues events in
memory (capped at 2,000) and posts them with the next batch — losing an hour's footfall
would make that day's conversion rate silently wrong, which is worse than a gap.

### What the cameras make possible

Conversion is the headline: footfall from cameras, orders from the POS, and the ratio that
neither produces alone. Beyond it:

- Queue wait against abandonment, by hour, per store
- Dwell against interaction in display zones — a display being read rather than shopped
- Occupancy peaks against staffing schedules
- Footfall trend independent of sales, which separates a traffic problem from a
  conversion problem

---

## Voice

### How it is wired

The browser holds the microphone. The server mints a ten-minute Azure Speech token, so the
subscription key never reaches the client and audio never transits our servers.

When Azure Speech is not configured, `/voice/token` returns `{"mode": "browser"}` rather
than an error, and the client uses the Web Speech API. This is why the microphone button is
never disabled just because Azure is not wired up yet.

Recognition is biased towards retail and QSR vocabulary — "attach rate", "daypart",
"like-for-like", "next best offer", "planogram". Generic speech models get exactly these
wrong, so the phrase list matters more than it looks.

### Speaking, not printing

A spoken answer is a different register from a written one. The copilot is told so
explicitly when the question arrives by voice: under sixty words, three sentences, one
number, one reason, one action.

`spoken_form()` then rewrites figures for the ear: `₹4,32,000` becomes "4.3 lakh rupees",
`8.4%` becomes "8.4 percent", and the answer is truncated to roughly three sentences. The
full detail stays on screen — the voice gives the headline, not the report.

TTS uses `narration-professional` style at a slightly reduced rate, because spoken analysis
is harder to follow than spoken prose.

### Languages

English (India, US, UK), Hindi, Tamil, Telugu, Marathi, Bengali, and Arabic for the UAE.
The tenant's country sets the default locale; a user can override it.

### What is not built

- **No wake word.** `"Hey ShopperMind"` is defined in the config and not implemented.
  Always-on listening in a shared office needs a consent conversation before it needs code.
- **No speaker identification.** Deliberate, and consistent with the camera position.
- **No voice in the store for customers.** The voice interface is for the marketing and
  operations team, not a customer-facing kiosk. A kiosk would be a different product with a
  different privacy posture.
