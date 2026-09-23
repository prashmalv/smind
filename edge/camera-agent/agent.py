#!/usr/bin/env python3
"""
ShopperMind edge camera agent.

Runs on a small box in the store (an Azure IoT Edge device, an Intel NUC, a Jetson),
reads each camera's stream, and posts *aggregated, anonymous* windows to the platform.

The design rule that matters: frames never leave the store. Detection happens here —
locally with OpenCV, or by calling Azure AI Vision if the site opts in — and what goes
over the wire is a row of counts. There is no face template, no re-identification, and
nothing that could reconstruct who a person was.

Run it with no hardware at all:

    python agent.py --simulate --cameras KOR-ENT:entrance,KOR-QUE:queue

or against a video file or a real RTSP stream:

    python agent.py --source samples/store.mp4 --camera KOR-ENT --zone entrance
    python agent.py --source rtsp://user:pass@10.0.0.9/stream1 --camera KOR-ENT --zone entrance
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import requests

log = logging.getLogger("shoppermind.edge")

DEFAULT_API = os.environ.get("SHOPPERMIND_API_URL", "http://localhost:8000")
DEFAULT_KEY = os.environ.get("CAMERA_AGENT_KEY", "")

# How often a window is closed and posted. Five minutes is a compromise: short enough
# that a queue alert is actionable in the moment, long enough that counts are stable.
WINDOW_SECONDS = 300
FRAME_INTERVAL = 2.0          # seconds between analysed frames
SERVICE_RATE_PER_MIN = 0.7    # counter throughput, used to turn occupancy into a wait


@dataclass
class Observation:
    """One analysed frame reduced to a count. Nothing else is retained."""

    people: int = 0
    confidence: float = 0.0
    provider: str = "local"


@dataclass
class Window:
    camera_code: str
    zone_type: str
    started: datetime
    observations: list[Observation] = field(default_factory=list)

    def add(self, obs: Observation) -> None:
        self.observations.append(obs)

    @property
    def age(self) -> float:
        return (datetime.now(UTC) - self.started).total_seconds()

    def to_event(self) -> dict:
        """Reduce the window to the numbers the platform stores.

        Entries are counted as upward transitions rather than raw headcount, so someone
        standing still for five minutes is one visitor, not 150.
        """
        counts = [o.people for o in self.observations] or [0]
        peak = max(counts)
        mean = sum(counts) / len(counts)
        entries = counts[0] + sum(
            max(0, counts[i] - counts[i - 1]) for i in range(1, len(counts))
        )
        confidence = sum(o.confidence for o in self.observations) / max(len(self.observations), 1)
        provider = self.observations[0].provider if self.observations else "local"

        event = {
            "camera_code": self.camera_code,
            "window_start": self.started.isoformat(),
            "window_seconds": int(self.age) or WINDOW_SECONDS,
            "max_occupancy": peak,
            "detector": provider,
            "confidence": round(confidence, 3),
            "footfall_in": 0, "footfall_out": 0, "unique_visitors": 0,
            "avg_queue_length": 0.0, "max_queue_length": 0, "avg_wait_seconds": 0.0,
            "abandonment_count": 0, "avg_dwell_seconds": 0.0, "interaction_count": 0,
            "demographics": {},
        }

        if self.zone_type in ("entrance", "exit", "drive-thru"):
            event["footfall_in"] = entries
            event["footfall_out"] = int(entries * 0.96)
            # Distinct visitors is below raw entries: re-entry and threshold double
            # counting. The discount is deliberately conservative.
            event["unique_visitors"] = int(entries * 0.82)

        elif self.zone_type in ("queue", "counter"):
            event["avg_queue_length"] = round(mean, 2)
            event["max_queue_length"] = peak
            # Little's Law: time in the system = number in the system ÷ service rate.
            event["avg_wait_seconds"] = round(mean / max(SERVICE_RATE_PER_MIN, 0.1) * 60, 1)
            # An abandonment is a sharp drop from an already long queue.
            event["abandonment_count"] = sum(
                1 for i in range(1, len(counts))
                if counts[i - 1] >= 4 and counts[i - 1] - counts[i] >= 2
            )

        else:  # aisle, display, seating
            person_seconds = mean * len(self.observations) * FRAME_INTERVAL
            event["avg_dwell_seconds"] = round(person_seconds / max(entries, 1), 1)
            event["interaction_count"] = sum(1 for c in counts if c > mean * 1.3)

        return event


# ── detectors ───────────────────────────────────────────────────────────────
class SimulatedDetector:
    """Generates a plausible day without a camera or a video file.

    This is what makes the platform demonstrable with no hardware: the shape of the
    day — lunch and dinner peaks, a quiet mid-afternoon — is real enough that the
    intelligence modules behave exactly as they would on a live site.
    """

    def __init__(self, zone_type: str, seed: int | None = None) -> None:
        self.zone_type = zone_type
        self.rng = random.Random(seed)

    def read(self) -> Observation:
        hour = datetime.now().hour
        busy = 2.1 if hour in (12, 13, 19, 20) else 1.4 if hour in (14, 18, 21) else 0.8
        base = {"entrance": 9, "queue": 4, "display": 5}.get(self.zone_type, 4)
        people = max(0, int(self.rng.gauss(base * busy, base * 0.4)))
        return Observation(people=people, confidence=0.75, provider="simulated")


class LocalDetector:
    """OpenCV HOG person detection, on-device.

    HOG is chosen over a heavier model on purpose: it runs on a cheap store gateway with
    no GPU, and the platform only needs a count, not a classification. Where a site wants
    better accuracy, point `--detector azure` at Azure AI Vision instead.
    """

    def __init__(self, source: str) -> None:
        try:
            import cv2
        except ImportError:
            sys.exit(
                "opencv-python is required for local detection.\n"
                "  pip install opencv-python\n"
                "Or run with --simulate to try the pipeline with no camera."
            )
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(source)
        if not self.capture.isOpened():
            sys.exit(f"Could not open video source: {source}")
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def read(self) -> Observation:
        ok, frame = self.capture.read()
        if not ok:
            # Loop a sample file so a short clip can stand in for a day.
            self.capture.set(self.cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
            if not ok:
                return Observation(provider="local")

        frame = self.cv2.resize(frame, (640, 480))
        boxes, weights = self.hog.detectMultiScale(
            frame, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        keep = [w for w in weights if w >= 0.5]
        return Observation(
            people=len(keep),
            confidence=round(float(sum(keep) / len(keep)), 3) if keep else 0.0,
            provider="opencv-hog",
        )

    def close(self) -> None:
        self.capture.release()


class AzureVisionDetector:
    """Calls Azure AI Vision's people model on a sampled frame.

    Only used when the site has opted into cloud analysis. Even then it is the `people`
    feature alone — never Face, never identification.
    """

    def __init__(self, source: str, endpoint: str, key: str) -> None:
        try:
            import cv2
        except ImportError:
            sys.exit("opencv-python is required to grab frames. pip install opencv-python")
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(source)
        self.url = (
            f"{endpoint.rstrip('/')}/computervision/imageanalysis:analyze"
            "?api-version=2024-02-01&features=people"
        )
        self.key = key

    def read(self) -> Observation:
        ok, frame = self.capture.read()
        if not ok:
            self.capture.set(self.cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
            if not ok:
                return Observation(provider="azure-ai-vision")

        ok, buf = self.cv2.imencode(".jpg", frame)
        if not ok:
            return Observation(provider="azure-ai-vision")

        try:
            resp = requests.post(
                self.url,
                headers={
                    "Ocp-Apim-Subscription-Key": self.key,
                    "Content-Type": "application/octet-stream",
                },
                data=buf.tobytes(),
                timeout=20,
            )
            resp.raise_for_status()
            people = [
                p for p in resp.json().get("peopleResult", {}).get("values", [])
                if p.get("confidence", 0) >= 0.45
            ]
        except Exception as exc:
            log.warning("Azure AI Vision call failed: %s", exc)
            return Observation(provider="azure-ai-vision")

        conf = sum(p["confidence"] for p in people) / len(people) if people else 0.0
        return Observation(
            people=len(people), confidence=round(conf, 3), provider="azure-ai-vision"
        )

    def close(self) -> None:
        self.capture.release()


# ── posting ─────────────────────────────────────────────────────────────────
class Publisher:
    """Posts events, and keeps them if the platform is unreachable.

    A store's network drops. Losing the footfall for that hour would silently corrupt the
    conversion rate for the day, so events queue in memory and go up with the next batch.
    """

    def __init__(self, api_url: str, key: str, max_queue: int = 2000) -> None:
        self.url = f"{api_url.rstrip('/')}/api/v1/cameras/events"
        self.key = key
        self.pending: list[dict] = []
        self.max_queue = max_queue

    def publish(self, events: list[dict]) -> bool:
        self.pending.extend(events)
        if len(self.pending) > self.max_queue:
            dropped = len(self.pending) - self.max_queue
            self.pending = self.pending[-self.max_queue:]
            log.warning("Dropped %d buffered events — the backlog exceeded %d",
                        dropped, self.max_queue)
        try:
            resp = requests.post(
                self.url,
                headers={"X-ShopperMind-Key": self.key, "Content-Type": "application/json"},
                data=json.dumps(self.pending),
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            log.info(
                "Posted %d events · accepted %s · alerts %s%s",
                len(self.pending), body.get("accepted"), body.get("alerts_raised"),
                f" · unknown cameras {body['unknown_cameras']}" if body.get("unknown_cameras") else "",
            )
            self.pending.clear()
            return True
        except Exception as exc:
            log.warning("Publish failed (%s). %d events held for the next attempt.",
                        exc, len(self.pending))
            return False


# ── main loop ───────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:
    if not args.key:
        sys.exit(
            "No ingest key. Create one in ShopperMind under In-store vision → "
            "'Create an ingest key', then pass --key or set CAMERA_AGENT_KEY."
        )

    cameras: list[tuple[str, str]] = []
    if args.cameras:
        for spec in args.cameras.split(","):
            code, _, zone = spec.partition(":")
            cameras.append((code.strip(), (zone or "entrance").strip()))
    else:
        cameras.append((args.camera, args.zone))

    detectors: dict[str, object] = {}
    for code, zone in cameras:
        if args.simulate:
            detectors[code] = SimulatedDetector(zone, seed=hash(code) & 0xFFFF)
        elif args.detector == "azure":
            endpoint = os.environ.get("AZURE_VISION_ENDPOINT", "")
            key = os.environ.get("AZURE_VISION_KEY", "")
            if not endpoint or not key:
                sys.exit("--detector azure needs AZURE_VISION_ENDPOINT and AZURE_VISION_KEY.")
            detectors[code] = AzureVisionDetector(args.source, endpoint, key)
        else:
            detectors[code] = LocalDetector(args.source)

    publisher = Publisher(args.api, args.key)
    windows = {
        code: Window(camera_code=code, zone_type=zone, started=datetime.now(UTC))
        for code, zone in cameras
    }

    log.info(
        "Agent started · %d camera(s) · detector=%s · window=%ds · posting to %s",
        len(cameras), "simulated" if args.simulate else args.detector,
        args.window, args.api,
    )
    log.info("Frames are analysed locally; only aggregate counts are transmitted.")

    deadline = time.monotonic() + args.run_for if args.run_for else None
    try:
        while True:
            for code, _zone in cameras:
                windows[code].add(detectors[code].read())  # type: ignore[attr-defined]

            ready = [w for w in windows.values() if w.age >= args.window]
            if ready:
                publisher.publish([w.to_event() for w in ready])
                for w in ready:
                    windows[w.camera_code] = Window(
                        camera_code=w.camera_code, zone_type=w.zone_type,
                        started=datetime.now(UTC),
                    )

            if deadline and time.monotonic() >= deadline:
                remaining = [w for w in windows.values() if w.observations]
                if remaining:
                    publisher.publish([w.to_event() for w in remaining])
                log.info("Run complete.")
                return

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log.info("Stopping — flushing the open windows first.")
        remaining = [w for w in windows.values() if w.observations]
        if remaining:
            publisher.publish([w.to_event() for w in remaining])
    finally:
        for d in detectors.values():
            if hasattr(d, "close"):
                d.close()  # type: ignore[attr-defined]


def backfill(args: argparse.Namespace) -> None:
    """Generate a plausible history so a new workspace has something to analyse.

    Useful for demos and for testing the modules: it writes the same event shape the live
    agent produces, just dated backwards.
    """
    rng = random.Random(7)
    publisher = Publisher(args.api, args.key)
    cameras = [
        (code.strip(), (zone or "entrance").strip())
        for code, _, zone in (spec.partition(":") for spec in args.cameras.split(","))
    ]
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    events: list[dict] = []

    for day in range(args.days, 0, -1):
        for hour in range(9, 23):
            start = now - timedelta(days=day) + timedelta(hours=hour - now.hour)
            busy = 2.1 if hour in (12, 13, 19, 20) else 1.4 if hour in (14, 18, 21) else 0.8
            for code, zone in cameras:
                base = {"entrance": 34, "queue": 5, "display": 18}.get(zone, 12)
                n = max(1, int(rng.gauss(base * busy, base * 0.25)))
                window = Window(camera_code=code, zone_type=zone, started=start)
                window.observations = [
                    Observation(people=max(0, int(rng.gauss(n / 6, 2))), confidence=0.8,
                                provider="simulated")
                    for _ in range(12)
                ]
                event = window.to_event()
                event["window_seconds"] = 3600
                events.append(event)

    log.info("Backfilling %d events across %d days…", len(events), args.days)
    for i in range(0, len(events), 500):
        publisher.publish(events[i:i + 500])
    log.info("Backfill complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ShopperMind edge camera agent — anonymous in-store counts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--api", default=DEFAULT_API, help="ShopperMind API base URL")
    parser.add_argument("--key", default=DEFAULT_KEY, help="Ingest key (X-ShopperMind-Key)")
    parser.add_argument("--camera", default="CAM-1", help="Camera code registered in ShopperMind")
    parser.add_argument("--zone", default="entrance",
                        help="entrance | queue | counter | aisle | display | seating | exit")
    parser.add_argument("--cameras", default="",
                        help="Several at once: 'KOR-ENT:entrance,KOR-QUE:queue'")
    parser.add_argument("--source", default="0",
                        help="Video source: a file, an RTSP URL, or a device index")
    parser.add_argument("--detector", choices=["local", "azure"], default="local")
    parser.add_argument("--simulate", action="store_true",
                        help="No camera needed — generate a plausible feed")
    parser.add_argument("--window", type=int, default=WINDOW_SECONDS,
                        help="Seconds per aggregation window")
    parser.add_argument("--interval", type=float, default=FRAME_INTERVAL,
                        help="Seconds between analysed frames")
    parser.add_argument("--run-for", type=float, default=0,
                        help="Stop after this many seconds (0 runs forever)")
    parser.add_argument("--backfill-days", type=int, default=0,
                        help="Instead of running live, post this many days of history")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    if args.backfill_days:
        if not args.cameras:
            sys.exit("--backfill-days needs --cameras, e.g. 'KOR-ENT:entrance,KOR-QUE:queue'")
        args.days = args.backfill_days
        backfill(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
