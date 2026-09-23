"""Frame analysis for in-store cameras.

Where the work happens is a deliberate choice. The edge agent (edge/camera-agent) runs on
a gateway in the store and does the per-frame work there; this module is the cloud-side
half, used when a tenant opts into cloud analysis for a camera. Either way what lands in
the database is an aggregate count, never a frame and never an identity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class FrameObservation:
    """What one analysed frame contributes to a window."""

    people: int = 0
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    confidence: float = 0.0
    provider: str = "local"


async def analyze_frame(image_bytes: bytes) -> FrameObservation:
    """Count people in a frame with Azure AI Vision.

    `people` is the only model we call. Not Face, not identification — the platform is
    built so that the question 'who was this person' cannot be answered from what it stores.
    """
    if not settings.vision_enabled:
        return FrameObservation(provider="unconfigured")

    url = (
        f"{settings.azure_vision_endpoint.rstrip('/')}"
        "/computervision/imageanalysis:analyze?api-version=2024-02-01&features=people"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": settings.azure_vision_key,
        "Content-Type": "application/octet-stream",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, content=image_bytes)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        log.warning("Azure AI Vision call failed", exc_info=True)
        return FrameObservation(provider="error")

    detections = [
        p for p in data.get("peopleResult", {}).get("values", [])
        if p.get("confidence", 0) >= 0.45
    ]
    boxes = [
        (b["boundingBox"]["x"], b["boundingBox"]["y"],
         b["boundingBox"]["w"], b["boundingBox"]["h"])
        for b in detections if "boundingBox" in b
    ]
    avg_conf = (
        sum(p.get("confidence", 0) for p in detections) / len(detections) if detections else 0.0
    )
    return FrameObservation(
        people=len(detections), boxes=boxes, confidence=round(avg_conf, 3),
        provider="azure-ai-vision",
    )


@dataclass
class WindowAggregate:
    """A window of observations reduced to the numbers the platform actually stores."""

    footfall_in: int = 0
    unique_visitors: int = 0
    max_occupancy: int = 0
    avg_queue_length: float = 0.0
    max_queue_length: int = 0
    avg_wait_seconds: float = 0.0
    abandonment_count: int = 0
    avg_dwell_seconds: float = 0.0
    interaction_count: int = 0
    confidence: float = 0.0
    detector: str = "local"


def aggregate_window(
    observations: list[FrameObservation],
    zone_type: str,
    seconds_per_frame: float,
    service_rate_per_minute: float = 2.5,
) -> WindowAggregate:
    """Reduce a window of frames to storable metrics.

    Occupancy → wait uses Little's Law: the time in the system is the number in the system
    divided by the rate they are served. That is a defensible estimate from counts alone,
    which is the point — it needs no tracking of individuals.
    """
    if not observations:
        return WindowAggregate()

    counts = [o.people for o in observations]
    peak = max(counts)
    mean = sum(counts) / len(counts)

    # Entries: count upward transitions rather than raw headcount, so a person standing
    # still for the whole window is not counted repeatedly.
    entries = sum(
        max(0, counts[i] - counts[i - 1]) for i in range(1, len(counts))
    ) + counts[0]

    agg = WindowAggregate(
        max_occupancy=peak,
        confidence=round(sum(o.confidence for o in observations) / len(observations), 3),
        detector=observations[0].provider,
    )

    if zone_type in ("entrance", "exit", "drive-thru"):
        agg.footfall_in = entries
        # Distinct visitors is lower than raw entries; the discount reflects re-entry and
        # double counting at the threshold, and is deliberately conservative.
        agg.unique_visitors = int(round(entries * 0.82))

    elif zone_type in ("queue", "counter"):
        agg.avg_queue_length = round(mean, 2)
        agg.max_queue_length = peak
        agg.avg_wait_seconds = round(mean / max(service_rate_per_minute, 0.1) * 60, 1)
        # An abandonment is a drop of two or more from an already long queue.
        agg.abandonment_count = sum(
            1 for i in range(1, len(counts))
            if counts[i - 1] >= 4 and counts[i - 1] - counts[i] >= 2
        )

    else:  # aisle, display, seating
        # Dwell from occupancy: total person-seconds divided by the people who passed through.
        person_seconds = mean * len(observations) * seconds_per_frame
        throughput = max(entries, 1)
        agg.avg_dwell_seconds = round(person_seconds / throughput, 1)
        # An interaction is a sustained stop — occupancy holding above the window mean.
        agg.interaction_count = sum(1 for c in counts if c > mean * 1.3)

    return agg
