"""In-store camera intelligence: registration, ingest, live view, alerts.

Ingest is authenticated with an API key rather than a user token, because the caller is a
gateway in a shop, not a person in a browser.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import (
    Principal,
    current_principal,
    hash_password,
    load_tenant_or_404,
    require_manager,
    verify_password,
)
from app.models.base import utcnow
from app.models.commerce import Store
from app.models.tenant import ApiKey, Tenant
from app.models.vision import ZONE_TYPES, Camera, CameraAlert, CameraEvent

router = APIRouter(prefix="/cameras", tags=["cameras"])

# Defaults a store manager can override per site. Expressed as the thing being watched,
# not as a raw number, because that is how the alert reads when it fires.
DEFAULT_THRESHOLDS = {
    "queue_length": 6,          # people waiting
    "wait_seconds": 240,        # four minutes
    "occupancy": 60,            # people in the space
    "offline_minutes": 15,
}


class CameraIn(BaseModel):
    code: str = Field(min_length=1, max_length=48)
    name: str = Field(min_length=1, max_length=160)
    store_id: str
    zone_type: str = "entrance"
    stream_url: str = ""
    mode: str = "simulated"
    blur_faces: bool = True
    retain_frames: bool = False
    retention_hours: int = 0


class CameraEventIn(BaseModel):
    """One aggregated window from the edge agent. Never a frame, never an identity."""

    camera_code: str
    window_start: datetime
    window_seconds: int = 300
    footfall_in: int = 0
    footfall_out: int = 0
    unique_visitors: int = 0
    max_occupancy: int = 0
    avg_queue_length: float = 0.0
    max_queue_length: int = 0
    avg_wait_seconds: float = 0.0
    abandonment_count: int = 0
    avg_dwell_seconds: float = 0.0
    interaction_count: int = 0
    demographics: dict[str, int] = Field(default_factory=dict)
    detector: str = "local"
    confidence: float = 0.0


# ── management ──────────────────────────────────────────────────────────────
@router.get("")
def list_cameras(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    cams = db.scalars(
        select(Camera).where(Camera.tenant_id == principal.tenant_id).order_by(Camera.name)
    ).all()
    stores = {
        s.id: s.name
        for s in db.scalars(select(Store).where(Store.tenant_id == principal.tenant_id)).all()
    }
    return [
        {
            "id": c.id, "code": c.code, "name": c.name, "store_id": c.store_id,
            "store_name": stores.get(c.store_id, ""), "zone_type": c.zone_type,
            "mode": c.mode, "is_active": c.is_active, "healthy": c.is_healthy,
            "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
            "blur_faces": c.blur_faces, "retain_frames": c.retain_frames,
            "retention_hours": c.retention_hours,
            # The stream URL is deliberately not returned — it is an edge-agent secret.
            "stream_configured": bool(c.stream_url),
        }
        for c in cams
    ]


@router.get("/zones")
def zones():
    return {"zone_types": list(ZONE_TYPES), "default_thresholds": DEFAULT_THRESHOLDS}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraIn,
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    if not tenant.camera_enabled:
        raise HTTPException(status_code=403,
                            detail="Camera intelligence is switched off for this workspace.")
    if payload.zone_type not in ZONE_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"zone_type must be one of {', '.join(ZONE_TYPES)}")

    store = db.get(Store, payload.store_id)
    if store is None or store.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Store not found")

    count = db.scalar(
        select(func.count()).select_from(Camera).where(Camera.tenant_id == tenant.id)) or 0
    if count >= tenant.limits["cameras"]:
        raise HTTPException(
            status_code=402,
            detail=f"The {tenant.plan} plan includes {tenant.limits['cameras']} cameras.",
        )

    exists = db.scalar(
        select(Camera).where(Camera.tenant_id == tenant.id, Camera.code == payload.code))
    if exists:
        raise HTTPException(status_code=409, detail="A camera with that code already exists")

    cam = Camera(tenant_id=tenant.id, **payload.model_dump())
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return {"id": cam.id, "code": cam.code, "name": cam.name, "mode": cam.mode}


@router.delete("/{camera_id}", status_code=204)
def delete_camera(
    camera_id: str,
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    cam = db.get(Camera, camera_id)
    if cam is None or cam.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam)
    db.commit()


@router.post("/keys", status_code=status.HTTP_201_CREATED)
def create_ingest_key(
    label: str = Body("Edge agent", embed=True),
    principal: Principal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Mint an ingest key for an edge agent. The raw key is shown exactly once."""
    raw = f"smk_{secrets.token_urlsafe(32)}"
    key = ApiKey(
        tenant_id=principal.tenant_id, label=label, key_hash=hash_password(raw), scope="ingest"
    )
    db.add(key)
    db.commit()
    return {
        "id": key.id, "label": key.label, "key": raw,
        "note": "Store this now — it is not retrievable again.",
    }


@router.get("/keys")
def list_keys(
    principal: Principal = Depends(require_manager), db: Session = Depends(get_db)
):
    keys = db.scalars(
        select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id)).all()
    return [
        {"id": k.id, "label": k.label, "scope": k.scope, "is_active": k.is_active,
         "call_count": k.call_count, "created_at": k.created_at.isoformat()}
        for k in keys
    ]


# ── ingest (machine caller) ─────────────────────────────────────────────────
def _tenant_from_key(db: Session, api_key: str | None) -> Tenant:
    if not api_key:
        raise HTTPException(status_code=401, detail="X-ShopperMind-Key header missing")
    for key in db.scalars(select(ApiKey).where(ApiKey.is_active.is_(True))).all():
        if verify_password(api_key, key.key_hash):
            key.call_count += 1
            tenant = db.get(Tenant, key.tenant_id)
            if tenant is None or not tenant.is_active:
                raise HTTPException(status_code=403, detail="Workspace is not active")
            return tenant
    raise HTTPException(status_code=401, detail="Invalid ingest key")


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def ingest_events(
    events: list[CameraEventIn],
    x_shoppermind_key: str | None = Header(None, alias="X-ShopperMind-Key"),
    db: Session = Depends(get_db),
):
    """Receive aggregated windows from an edge agent, and raise alerts on breach."""
    tenant = _tenant_from_key(db, x_shoppermind_key)
    cams = {
        c.code: c
        for c in db.scalars(select(Camera).where(Camera.tenant_id == tenant.id)).all()
    }

    accepted, unknown, alerts = 0, [], 0
    for e in events:
        cam = cams.get(e.camera_code)
        if cam is None:
            unknown.append(e.camera_code)
            continue

        db.add(CameraEvent(
            tenant_id=tenant.id, camera_id=cam.id, store_id=cam.store_id,
            zone_type=cam.zone_type, window_start=e.window_start,
            window_seconds=e.window_seconds, footfall_in=e.footfall_in,
            footfall_out=e.footfall_out, unique_visitors=e.unique_visitors,
            max_occupancy=e.max_occupancy, avg_queue_length=e.avg_queue_length,
            max_queue_length=e.max_queue_length, avg_wait_seconds=e.avg_wait_seconds,
            abandonment_count=e.abandonment_count, avg_dwell_seconds=e.avg_dwell_seconds,
            interaction_count=e.interaction_count,
            demographics=json.dumps(e.demographics), detector=e.detector,
            confidence=e.confidence,
        ))
        cam.last_seen_at = utcnow()
        accepted += 1
        alerts += _raise_alerts(db, tenant.id, cam, e)

    db.commit()
    return {"accepted": accepted, "unknown_cameras": unknown, "alerts_raised": alerts}


def _raise_alerts(db: Session, tenant_id: str, cam: Camera, e: CameraEventIn) -> int:
    """Alerts fire on the window that breached, not on a daily roll-up — a queue alert
    that arrives tomorrow is a report, not an alert."""
    raised = 0
    checks = [
        ("queue_breach", e.max_queue_length, DEFAULT_THRESHOLDS["queue_length"], "high",
         f"Queue reached {e.max_queue_length} people at {cam.name}"),
        ("wait_breach", e.avg_wait_seconds, DEFAULT_THRESHOLDS["wait_seconds"], "high",
         f"Average wait hit {e.avg_wait_seconds:.0f} seconds at {cam.name}"),
        ("occupancy_breach", e.max_occupancy, DEFAULT_THRESHOLDS["occupancy"], "medium",
         f"Occupancy reached {e.max_occupancy} at {cam.name}"),
    ]
    for alert_type, observed, threshold, severity, message in checks:
        if observed <= threshold:
            continue
        # One alert per camera per type per hour — an alert that fires every window is noise.
        recent = db.scalar(
            select(CameraAlert).where(
                CameraAlert.tenant_id == tenant_id, CameraAlert.camera_id == cam.id,
                CameraAlert.alert_type == alert_type,
                CameraAlert.raised_at >= utcnow() - timedelta(hours=1),
            )
        )
        if recent:
            continue
        db.add(CameraAlert(
            tenant_id=tenant_id, camera_id=cam.id, store_id=cam.store_id,
            alert_type=alert_type, severity=severity, message=message,
            observed_value=float(observed), threshold_value=float(threshold),
            raised_at=utcnow(),
        ))
        raised += 1
    return raised


# ── live view and alerts ────────────────────────────────────────────────────
@router.get("/live")
def live(
    minutes: int = Query(60, ge=5, le=1440),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Current state across the estate, as the operations screen renders it."""
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    rows = db.execute(
        select(
            CameraEvent.camera_id, CameraEvent.store_id, CameraEvent.zone_type,
            func.sum(CameraEvent.footfall_in), func.avg(CameraEvent.avg_queue_length),
            func.max(CameraEvent.max_queue_length), func.avg(CameraEvent.avg_wait_seconds),
            func.sum(CameraEvent.abandonment_count), func.avg(CameraEvent.avg_dwell_seconds),
            func.max(CameraEvent.window_start),
        )
        .where(CameraEvent.tenant_id == principal.tenant_id, CameraEvent.window_start >= since)
        .group_by(CameraEvent.camera_id, CameraEvent.store_id, CameraEvent.zone_type)
    ).all()

    cams = {
        c.id: c for c in db.scalars(
            select(Camera).where(Camera.tenant_id == principal.tenant_id)).all()
    }
    stores = {
        s.id: s.name for s in db.scalars(
            select(Store).where(Store.tenant_id == principal.tenant_id)).all()
    }

    feeds = []
    for (cam_id, store_id, zone, foot, avg_q, max_q, wait, aband, dwell, last) in rows:
        cam = cams.get(cam_id)
        # A zone only produces the metrics it can measure. Reporting 0 footfall for a
        # queue camera would read as "nobody came in" when the truth is "this camera
        # does not count entries" — null renders as "—" instead.
        counts_entries = zone in ("entrance", "exit", "drive-thru")
        measures_queue = zone in ("queue", "counter")
        measures_dwell = zone in ("aisle", "display", "seating")

        feeds.append({
            "camera_id": cam_id,
            "camera_name": cam.name if cam else cam_id,
            "camera_code": cam.code if cam else "",
            "store_name": stores.get(store_id, ""),
            "zone_type": zone,
            "mode": cam.mode if cam else "unknown",
            "footfall": int(foot or 0) if counts_entries else None,
            "avg_queue_length": round(float(avg_q or 0), 1) if measures_queue else None,
            "max_queue_length": int(max_q or 0) if measures_queue else None,
            "avg_wait_seconds": round(float(wait or 0), 1) if measures_queue else None,
            "abandonments": int(aband or 0) if measures_queue else None,
            "avg_dwell_seconds": round(float(dwell or 0), 1) if measures_dwell else None,
            "last_window": last.isoformat() if last else None,
            "healthy": cam.is_healthy if cam else False,
        })
    feeds.sort(key=lambda f: (f["max_queue_length"] or 0), reverse=True)

    offline = [
        {"camera_id": c.id, "camera_name": c.name, "store_name": stores.get(c.store_id, ""),
         "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None}
        for c in cams.values() if c.is_active and not c.is_healthy
    ]

    return {
        "window_minutes": minutes,
        "cameras_total": len(cams),
        # Two different questions: did this camera send anything during the window, and
        # has it sent anything in the last fifteen minutes. A camera can have reported
        # all day and still be silent right now, so these are reported separately
        # rather than collapsed into one misleading figure.
        "cameras_reporting": len(feeds),
        "cameras_stale": len(offline),
        "cameras_offline": offline,
        "total_footfall": sum(f["footfall"] or 0 for f in feeds),
        "feeds": feeds,
    }


@router.get("/alerts")
def alerts(
    unresolved_only: bool = True,
    limit: int = Query(50, le=200),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    stmt = select(CameraAlert).where(CameraAlert.tenant_id == principal.tenant_id)
    if unresolved_only:
        stmt = stmt.where(CameraAlert.resolved_at.is_(None))
    rows = db.scalars(stmt.order_by(CameraAlert.raised_at.desc()).limit(limit)).all()
    stores = {
        s.id: s.name for s in db.scalars(
            select(Store).where(Store.tenant_id == principal.tenant_id)).all()
    }
    return [
        {
            "id": a.id, "alert_type": a.alert_type, "severity": a.severity,
            "message": a.message, "store_name": stores.get(a.store_id, ""),
            "observed_value": a.observed_value, "threshold_value": a.threshold_value,
            "raised_at": a.raised_at.isoformat(),
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        }
        for a in rows
    ]


@router.patch("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    alert = db.get(CameraAlert, alert_id)
    if alert is None or alert.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.resolved_at = utcnow()
    alert.acknowledged_by = principal.user_id
    db.commit()
    return {"id": alert.id, "resolved": True}
