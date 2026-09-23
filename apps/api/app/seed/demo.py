"""Seed a new workspace with a realistic estate.

The point is not volume, it is *signal*. A random dataset makes every module report
"nothing significant", which makes the product look broken on day one. So this seeder
plants specific, defensible patterns and lets the modules find them honestly:

  · one item in decline, against a category that is flat  → menu intelligence
  · one store with a queue problem and low conversion      → store vision + store intelligence
  · delivery complaints concentrated in the evening        → voice of customer
  · a price-elastic item and an inelastic one              → price sensitivity
  · one campaign that lost money                           → campaign intelligence
  · a rising 'spicy' theme not yet on the menu             → trend detection
  · a cohort that stopped ordering 50+ days ago            → churn intelligence
  · fries and beverages under-attaching to burgers         → basket analysis

Nothing is written as a conclusion — the numbers are generated, and the modules derive
the findings from them the same way they would from a real POS feed.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.commerce import Customer, Order, OrderItem, Product, Store
from app.models.signals import Campaign, CompetitorSignal, Feedback
from app.models.tenant import Tenant
from app.models.vision import Camera, CameraEvent
from app.seed.catalogues import (
    COMPETITOR_SIGNALS,
    COMPETITORS,
    NEGATIVE_FEEDBACK,
    NEUTRAL_FEEDBACK,
    POSITIVE_FEEDBACK,
    QSR_MENU,
    QSR_PAIRS,
    RETAIL_CATALOGUE,
    RETAIL_PAIRS,
    STORES,
    TREND_FEEDBACK,
)
from app.services.azure_language import enrich_sync

log = logging.getLogger(__name__)

DAYS = 75
AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55+"]
CHANNELS_QSR = ["dine-in", "takeaway", "delivery", "drive-thru"]
CHANNELS_RETAIL = ["in-store", "online", "delivery"]


def _daypart(dt: datetime) -> str:
    h = dt.hour
    if h < 11:
        return "breakfast"
    if h < 15:
        return "lunch"
    if h < 18:
        return "afternoon"
    if h < 22:
        return "dinner"
    return "late night"


def seed_tenant(db: Session, tenant: Tenant, days: int = DAYS) -> dict:
    """Populate a workspace. Idempotent by tenant — a second call is a no-op."""
    rng = random.Random(hash(tenant.id) & 0xFFFFFFFF)
    existing = db.query(Store).filter(Store.tenant_id == tenant.id).count()
    if existing:
        return {"skipped": True, "reason": "Workspace already has data"}

    is_retail = tenant.vertical in ("retail", "grocery", "pharmacy", "fashion")
    catalogue = RETAIL_CATALOGUE if is_retail else QSR_MENU
    pairings = RETAIL_PAIRS if is_retail else QSR_PAIRS
    channels = CHANNELS_RETAIL if is_retail else CHANNELS_QSR
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    # ── stores ──────────────────────────────────────────────────────────────
    n_stores = min(len(STORES), 10)
    stores: list[Store] = []
    for code, name, city, state, region, fmt in STORES[:n_stores]:
        s = Store(
            tenant_id=tenant.id, code=code, name=name, city=city, state=state,
            region=region, format=fmt, is_active=True,
            floor_area_sqft=rng.randint(900, 3200),
            opened_on=(now - timedelta(days=rng.randint(200, 2000))).date(),
        )
        db.add(s)
        stores.append(s)
    db.flush()

    # The store carrying the planted operational problem.
    problem_store = stores[0]

    # ── catalogue ───────────────────────────────────────────────────────────
    products: list[Product] = []
    for sku, name, category, price, cost, is_combo in catalogue:
        p = Product(
            tenant_id=tenant.id, sku=sku, name=name, category=category,
            price=float(price), cost=float(cost), is_combo=is_combo, is_active=True,
        )
        db.add(p)
        products.append(p)
    db.flush()

    by_name = {p.name: p for p in products}
    # Planted roles. Falls back gracefully if a vertical lacks the named item.
    declining = by_name.get("Chicken Burger") or by_name.get("Shampoo 340ml") or products[0]
    elastic = by_name.get("Cola 400ml") or by_name.get("Potato Chips 150g") or products[-1]
    inelastic = by_name.get("Cold Coffee") or by_name.get("Milk 1L") or products[1]
    attach_targets = [
        p for p in products
        if p.category in ("Sides", "Beverages", "Snacks", "Bakery")
    ] or products[:3]
    anchors = [
        p for p in products
        if p.category in ("Burgers", "Wraps", "Staples", "Dairy")
    ] or products[:4]

    # ── customers ───────────────────────────────────────────────────────────
    # Built as plain rows and bulk-inserted. A chain this size has tens of thousands of
    # identifiable customers, most of whom buy once or twice — that long tail is what
    # makes the repeat rate and the churn scores mean anything.
    from app.models.base import new_id

    n_customers = 12000
    customer_rows: list[dict] = []
    for i in range(n_customers):
        home = rng.choice(stores)
        customer_rows.append({
            "id": new_id(), "tenant_id": tenant.id, "external_id": f"CUST{i + 10000}",
            "display_name": f"Customer {i + 10000}",
            "age_band": rng.choices(AGE_BANDS, weights=[26, 34, 20, 13, 7])[0],
            "gender": rng.choice(["female", "male", ""]),
            "phone_hash": "", "email_hash": "",
            "city": home.city, "home_store_id": home.id,
            "signup_channel": rng.choice(["app", "web", "in-store", "delivery-partner"]),
            "first_order_at": None, "last_order_at": None,
            "order_count": 0, "lifetime_value": 0.0, "avg_basket_value": 0.0,
        })
    db.bulk_insert_mappings(Customer, customer_rows)

    # Behavioural cohorts — this is what makes segmentation produce distinct groups
    # rather than one undifferentiated blob. Indices into customer_rows, by id.
    ids = [c["id"] for c in customer_rows]
    home_of = {c["id"]: c["home_store_id"] for c in customer_rows}
    loyal = ids[:900]                    # frequent, full price
    value = ids[900:3000]                # discount-driven
    convenience = ids[3000:4800]         # delivery/online heavy
    premium = ids[4800:5600]             # large baskets
    occasional = ids[5600:11400]         # the long tail: one or two visits
    lapsing = ids[11400:]                # stopped ordering partway through

    cohort_of: dict[str, str] = {}
    for name, group in (("loyal", loyal), ("value", value), ("convenience", convenience),
                        ("premium", premium), ("occasional", occasional),
                        ("lapsing", lapsing)):
        for cid in group:
            cohort_of[cid] = name

    # Aggregates accumulated in Python, written back in one bulk update at the end.
    agg: dict[str, dict] = {}

    # ── orders ──────────────────────────────────────────────────────────────
    # Rows are built in memory with pre-assigned ids and inserted in bulk. Adding
    # each order through the ORM and flushing to obtain its id costs a round trip per
    # order, which turns signup into a thirty-second wait on a realistic volume.
    from app.models.base import new_id

    order_rows: list[dict] = []
    item_rows: list[dict] = []
    # (store_id, date, hour) -> orders. The camera feed is derived from this, so
    # footfall and conversion are consistent with each other the way real data is.
    demand: dict[tuple[str, object, int], int] = {}

    order_no = 0
    for day_offset in range(days, 0, -1):
        day = now - timedelta(days=day_offset)
        is_weekend = day.weekday() >= 5
        # A gentle decline across the most recent three weeks, so a period-over-period
        # comparison has something real to explain.
        recency_factor = 0.88 if day_offset <= 21 else 1.0

        for store in stores:
            store_pull = 1.25 if store.format in ("mall", "high-street") else 1.0
            volume = int(rng.gauss(96 if is_weekend else 72, 11) * recency_factor * store_pull)

            for _ in range(max(volume, 12)):
                cohort_pool = rng.choices(
                    [loyal, value, convenience, premium, occasional, lapsing],
                    weights=[30, 26, 18, 10, 14, 2],
                )[0]
                customer_id = rng.choice(cohort_pool)
                cohort = cohort_of[customer_id]

                # Lapsing customers stop entirely partway through the window.
                if cohort == "lapsing" and day_offset < 50:
                    continue

                # Roughly half of quick-service transactions are never tied to a known
                # customer — no app, no loyalty scan, cash at the counter. Pretending
                # otherwise would make every retention number flattering and wrong.
                identified = rng.random() > 0.48

                hour = rng.choices(
                    [8, 10, 12, 13, 14, 17, 19, 20, 21, 22],
                    weights=[4, 6, 14, 16, 8, 9, 15, 14, 9, 5],
                )[0]
                placed = day.replace(hour=hour, minute=rng.randint(0, 59))

                channel = rng.choice(channels)
                if cohort == "convenience":
                    pick = rng.choice(["delivery", "online", "takeaway"])
                    channel = pick if pick in channels else channels[-1]

                # Basket construction.
                basket: list[tuple[Product, int]] = []
                anchor = rng.choice(anchors)
                # The planted decline: this item appears less often in the recent window.
                if anchor.id == declining.id and day_offset <= 28 and rng.random() < 0.42:
                    anchor = rng.choice([a for a in anchors if a.id != declining.id] or anchors)
                basket.append((anchor, 1))

                # Attachment — deliberately weak at the problem store, so basket analysis
                # and store intelligence both have a real gap to find.
                attach_p = {"loyal": 0.62, "premium": 0.7, "value": 0.34,
                            "convenience": 0.42, "occasional": 0.3, "lapsing": 0.35}[cohort]
                if store.id == problem_store.id:
                    attach_p *= 0.55
                if rng.random() < attach_p and attach_targets:
                    # Two thirds of add-ons follow the anchor's usual partner, the rest
                    # are anything. That ratio is what separates a real pairing from
                    # noise once the association rules are computed.
                    partner = by_name.get(pairings.get(anchor.name, ""))
                    chosen = partner if partner is not None and rng.random() < 0.68 \
                        else rng.choice(attach_targets)
                    basket.append((chosen, 1))
                if cohort == "premium" and rng.random() < 0.55:
                    basket.append((rng.choice(products), 1))
                if rng.random() < 0.18:
                    basket.append((rng.choice(products), rng.randint(1, 2)))

                gross = 0.0
                lines = []
                for product, qty in basket:
                    unit = product.price
                    # Price variation over time, so elasticity is estimable rather than flat.
                    if product.id == elastic.id:
                        unit = round(product.price * rng.choice([0.8, 0.88, 1.0, 1.0, 1.15]), 2)
                        # Lower price genuinely pulls more units — this is the signal the
                        # price-sensitivity module is meant to recover.
                        if unit < product.price and rng.random() < 0.55:
                            qty += 1
                    elif product.id == inelastic.id:
                        unit = round(product.price * rng.choice([0.92, 1.0, 1.0, 1.1]), 2)
                    elif rng.random() < 0.12:
                        unit = round(product.price * rng.choice([0.9, 1.05]), 2)
                    lines.append((product, qty, unit))
                    gross += unit * qty

                discount = 0.0
                if cohort == "value" and rng.random() < 0.62:
                    discount = round(gross * rng.choice([0.1, 0.15, 0.2]), 2)
                elif rng.random() < 0.12:
                    discount = round(gross * 0.1, 2)

                fulfilment = rng.gauss(14, 4)
                if store.id == problem_store.id and 19 <= hour <= 21:
                    fulfilment = rng.gauss(31, 7)   # the planted evening problem

                order_no += 1
                order_id = new_id()
                net = round(gross - discount, 2)
                order_rows.append({
                    "id": order_id, "tenant_id": tenant.id,
                    "external_id": f"ORD{order_no:07d}", "store_id": store.id,
                    "customer_id": customer_id if identified else None,
                    "placed_at": placed, "channel": channel,
                    "daypart": _daypart(placed), "gross_amount": round(gross, 2),
                    "discount_amount": discount, "net_amount": net,
                    "item_count": sum(q for _, q, _ in lines),
                    "campaign_id": None,
                    "fulfilment_minutes": round(max(fulfilment, 4), 1),
                })
                for product, qty, unit in lines:
                    item_rows.append({
                        "id": new_id(), "tenant_id": tenant.id, "order_id": order_id,
                        "product_id": product.id, "quantity": qty, "unit_price": unit,
                        "line_amount": round(unit * qty, 2),
                        "is_addon": product in attach_targets, "notes": "",
                    })

                key = (store.id, day.date(), hour)
                demand[key] = demand.get(key, 0) + 1

                if identified:
                    a = agg.setdefault(
                        customer_id,
                        {"order_count": 0, "lifetime_value": 0.0,
                         "first_order_at": placed, "last_order_at": placed},
                    )
                    a["order_count"] += 1
                    a["lifetime_value"] += net
                    a["last_order_at"] = max(a["last_order_at"], placed)
                    a["first_order_at"] = min(a["first_order_at"], placed)

    db.bulk_insert_mappings(Order, order_rows)
    db.bulk_insert_mappings(OrderItem, item_rows)
    orders_created = len(order_rows)

    db.bulk_update_mappings(Customer, [
        {
            "id": cid,
            "order_count": a["order_count"],
            "lifetime_value": round(a["lifetime_value"], 2),
            "avg_basket_value": round(a["lifetime_value"] / max(a["order_count"], 1), 2),
            "first_order_at": a["first_order_at"],
            "last_order_at": a["last_order_at"],
        }
        for cid, a in agg.items()
    ])
    db.flush()

    # ── feedback ────────────────────────────────────────────────────────────
    feedback_created = 0
    for day_offset in range(days, 0, -1):
        day = now - timedelta(days=day_offset)
        for _ in range(rng.randint(4, 11)):
            # The planted trend grows in the recent window.
            trend_chance = 0.16 if day_offset <= 30 else 0.03
            if rng.random() < trend_chance:
                body, hour = rng.choice(TREND_FEEDBACK), rng.randint(11, 21)
            else:
                roll = rng.random()
                if roll < 0.52:
                    body, hour = rng.choice(POSITIVE_FEEDBACK), rng.randint(9, 22)
                elif roll < 0.85:
                    body = rng.choice(NEGATIVE_FEEDBACK)
                    # Delivery complaints cluster in the evening — the doc's 7–9 PM finding.
                    hour = rng.randint(19, 21) if "deliver" in body.lower() else rng.randint(9, 22)
                else:
                    body, hour = rng.choice(NEUTRAL_FEEDBACK), rng.randint(9, 22)

            # The problem store draws more than its share of negatives.
            store = (problem_store if rng.random() < 0.3 and "wait" in body.lower()
                     else rng.choice(stores))
            enriched = enrich_sync(body)
            rating = {"positive": rng.choice([4, 5]), "negative": rng.choice([1, 2]),
                      "neutral": 3}[enriched["sentiment"]]
            db.add(Feedback(
                tenant_id=tenant.id,
                source=rng.choices(["review", "social", "survey", "complaint", "chat"],
                                   weights=[40, 22, 18, 14, 6])[0],
                channel_name=rng.choice(["Google", "Zomato", "Swiggy", "In-app", "Instagram"]),
                store_id=store.id, captured_at=day.replace(hour=hour, minute=rng.randint(0, 59)),
                body=enriched["body"], rating=float(rating),
                sentiment=enriched["sentiment"], sentiment_score=enriched["sentiment_score"],
                themes=enriched["themes"],
                is_actionable=enriched["sentiment"] == "negative",
            ))
            feedback_created += 1
        if day_offset % 20 == 0:
            db.flush()

    # ── campaigns ───────────────────────────────────────────────────────────
    campaign_specs = [
        ("Weekend Value Bundle", "bundle", "app", 15, "value_seekers", 42000, 0.22, 3.1),
        ("Lapsed Win-back 20%", "winback", "sms", 20, "lapsed_customers", 28000, 0.14, 2.4),
        ("Loyalty Double Points", "loyalty", "app", 0, "frequency_customers", 35000, 0.31, 4.2),
        ("New Item Launch Blast", "launch", "email", 10, "all", 55000, 0.06, 0.7),
        ("Evening Flat 25% Off", "discount", "app", 25, "all", 68000, 0.28, 0.9),
        ("Premium Combo Push", "bundle", "app", 5, "premium_customers", 22000, 0.19, 3.8),
    ]
    for name, objective, channel, disc, segment, budget, redeem_rate, roi in campaign_specs:
        starts = (now - timedelta(days=rng.randint(30, 80))).date()
        reach = rng.randint(4000, 22000)
        redemptions = int(reach * redeem_rate)
        db.add(Campaign(
            tenant_id=tenant.id, name=name, objective=objective, channel=channel,
            offer_text=f"{disc}% off" if disc else "Double loyalty points",
            discount_pct=float(disc), target_segment=segment, starts_on=starts,
            ends_on=starts + timedelta(days=14), budget=float(budget), reach=reach,
            redemptions=redemptions, attributed_revenue=round(budget * roi, 0),
            status="completed",
        ))

    # ── competitor signals ──────────────────────────────────────────────────
    for competitor, avg_price in COMPETITORS:
        for signal_type, body in COMPETITOR_SIGNALS:
            enriched = enrich_sync(body)
            db.add(CompetitorSignal(
                tenant_id=tenant.id, competitor_name=competitor, signal_type=signal_type,
                city=rng.choice([s.city for s in stores]),
                observed_at=now - timedelta(days=rng.randint(1, 45)),
                body=body, sentiment=enriched["sentiment"],
                price_point=round(avg_price * rng.uniform(0.9, 1.1), 0)
                if signal_type in ("price", "offer") else None,
                source_url="",
            ))

    # ── cameras and their events ────────────────────────────────────────────
    cameras: list[Camera] = []
    for store in stores[:6]:
        for zone, suffix in (("entrance", "ENT"), ("queue", "QUE"), ("display", "DSP")):
            cam = Camera(
                tenant_id=tenant.id, code=f"{store.code}-{suffix}",
                name=f"{store.name} — {zone.title()}", store_id=store.id, zone_type=zone,
                mode="simulated", is_active=True, last_seen_at=now,
                blur_faces=True, retain_frames=False, retention_hours=0,
            )
            db.add(cam)
            cameras.append(cam)
    db.flush()

    # Camera events are derived from the orders actually generated above, not invented
    # separately. Footfall = orders ÷ conversion, so the two sources agree — which is
    # the whole point of joining them, and what makes the conversion finding meaningful
    # rather than an artefact of two unrelated random walks.
    from app.models.base import new_id

    CONVERSION = {}          # store_id -> the rate this store actually converts at
    for store in stores:
        base = rng.uniform(0.38, 0.52)
        if store.id == problem_store.id:
            base = 0.24      # the planted problem: footfall is fine, conversion is not
        CONVERSION[store.id] = base

    vision_days = min(days, 30)
    event_rows: list[dict] = []
    for day_offset in range(vision_days, 0, -1):
        day = now - timedelta(days=day_offset)
        for cam in cameras:
            is_problem = cam.store_id == problem_store.id
            conv = CONVERSION[cam.store_id]
            for hour in range(9, 23):
                window = day.replace(hour=hour, minute=0)
                orders_here = demand.get((cam.store_id, day.date(), hour), 0)
                # Even a dead hour has passers-by; a busy hour is driven by real demand.
                footfall = max(int(round(orders_here / conv)) + rng.randint(-1, 2), 1)
                base = {"id": new_id(), "tenant_id": tenant.id, "camera_id": cam.id,
                        "store_id": cam.store_id, "window_start": window,
                        "window_seconds": 3600, "detector": "simulated"}

                if cam.zone_type == "entrance":
                    event_rows.append({
                        **base, "zone_type": "entrance", "footfall_in": footfall,
                        "footfall_out": int(footfall * 0.96),
                        "unique_visitors": int(footfall * 0.82),
                        "max_occupancy": max(int(footfall * 0.4), 1),
                        "avg_queue_length": 0.0, "max_queue_length": 0,
                        "avg_wait_seconds": 0.0, "abandonment_count": 0,
                        "avg_dwell_seconds": 0.0, "interaction_count": 0,
                        "demographics": json.dumps({
                            "18-24": int(footfall * 0.26), "25-34": int(footfall * 0.34),
                            "35-44": int(footfall * 0.2), "45+": int(footfall * 0.2),
                        }),
                        "confidence": 0.88,
                    })
                elif cam.zone_type == "queue":
                    # M/M/1: queue length from utilisation, wait from queue length.
                    # Arrivals are this hour's actual footfall; capacity is the counter's
                    # service rate. As utilisation approaches 1 the queue grows sharply,
                    # which is exactly why an understaffed evening hour is not a linear
                    # problem and why the finding is worth surfacing.
                    # One counter takes roughly 85 seconds per customer end to end.
                    service_per_min = 0.7
                    if is_problem and hour in (19, 20, 21):
                        service_per_min = 0.42  # the planted evening bottleneck
                    capacity = service_per_min * 60
                    # Utilisation is capped below 1: past that the queue is unbounded in
                    # theory, while in practice people leave — which is what the
                    # abandonment count below represents.
                    rho = min(footfall / max(capacity, 1), 0.9)
                    avg_q = min((rho ** 2) / max(1 - rho, 0.1) * rng.uniform(0.85, 1.2), 12)
                    wait = avg_q / service_per_min * 60   # seconds
                    event_rows.append({
                        **base, "zone_type": "queue", "footfall_in": 0, "footfall_out": 0,
                        "unique_visitors": 0,
                        "avg_queue_length": round(avg_q, 2),
                        "max_queue_length": int(avg_q * 1.8),
                        "avg_wait_seconds": round(wait, 1),
                        "abandonment_count": int(max(0.0, avg_q - 5) * rng.uniform(0.5, 2)),
                        "max_occupancy": int(avg_q * 2),
                        "avg_dwell_seconds": 0.0, "interaction_count": 0,
                        "demographics": "{}", "confidence": 0.84,
                    })
                else:  # display
                    busy = 1.0 + (footfall / 25)
                    dwell = max(rng.gauss(30 * busy, 7), 5)
                    event_rows.append({
                        **base, "zone_type": "display",
                        "footfall_in": max(int(footfall * 0.7), 1), "footfall_out": 0,
                        "unique_visitors": 0, "max_occupancy": max(int(footfall * 0.3), 1),
                        "avg_queue_length": 0.0, "max_queue_length": 0,
                        "avg_wait_seconds": 0.0, "abandonment_count": 0,
                        "avg_dwell_seconds": round(dwell, 1),
                        "interaction_count": int(footfall * 0.7 * rng.uniform(0.12, 0.22)),
                        "demographics": "{}", "confidence": 0.8,
                    })

    db.bulk_insert_mappings(CameraEvent, event_rows)
    events_created = len(event_rows)

    db.commit()

    summary = {
        "stores": len(stores), "products": len(products), "customers": len(customer_rows),
        "orders": orders_created, "feedback": feedback_created,
        "campaigns": len(campaign_specs), "cameras": len(cameras),
        "camera_events": events_created, "days": days,
    }
    log.info("Seeded tenant %s (%s): %s", tenant.slug, tenant.vertical, summary)
    return summary
