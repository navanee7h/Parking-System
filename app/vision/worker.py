"""CCTV worker: reads camera streams, detects occupancy + plates, pushes to the API.

Run one per camera group (can be on an edge box next to the NVR):

    python -m app.vision.worker --server http://localhost:8000 --camera CAM-A-WEST

Set PARKING_API_KEY to the same value as the server.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import cv2

from .anpr import EasyOCRPlateReader, PlateRead, assign_to_slot, merge_reads
from .occupancy import OccupancyDetector

PLATE_WINDOW = 5  # merge this many recent reads per slot


def post(server: str, path: str, body: dict) -> None:
    req = urllib.request.Request(
        server.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": os.getenv("PARKING_API_KEY", "dev-key")})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:  # keep running even if the server blips
        print(f"[worker] POST {path} failed: {e}")


def run(server: str, cam: dict, reader) -> None:
    ref = None
    if cam.get("reference_image") and Path(cam["reference_image"]).exists():
        ref = cv2.imread(cam["reference_image"])
    det = OccupancyDetector(cam["slots"], reference=ref)
    recent: dict[str, list[PlateRead]] = defaultdict(list)
    cap = cv2.VideoCapture(cam["source"])
    every = float(cam.get("sample_every_s", 2.0))
    print(f"[worker] {cam['id']}: watching {len(cam['slots'])} slots from {cam['source']}")

    while True:
        ok, frame = cap.read()
        if not ok:
            print(f"[worker] {cam['id']}: no frame, reconnecting in 5s")
            time.sleep(5)
            cap.release()
            cap = cv2.VideoCapture(cam["source"])
            continue

        changed = det.update(frame)
        if changed:
            post(server, "/api/ingest/occupancy", {"camera_id": cam["id"], "slots": changed})
            for sid, occ in changed.items():
                if not occ:
                    recent.pop(sid, None)

        if reader is not None:
            for r in reader.read(frame):
                sid = assign_to_slot(r, cam["slots"])
                if sid is None:
                    continue
                recent[sid] = (recent[sid] + [r])[-PLATE_WINDOW:]
                merged = merge_reads(recent[sid])
                post(server, "/api/ingest/plate", {"camera_id": cam["id"], "slot_id": sid,
                                                   "plate": merged.text, "confidence": merged.confidence})
        # skip buffered frames so we always look at "now"
        t_end = time.time() + every
        while time.time() < t_end:
            cap.grab()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--config", default="config/lot.json")
    ap.add_argument("--camera", required=True, help="camera id from config")
    ap.add_argument("--no-ocr", action="store_true", help="occupancy only")
    args = ap.parse_args()
    cams = {c["id"]: c for c in json.loads(Path(args.config).read_text())["cameras"]}
    reader = None if args.no_ocr else EasyOCRPlateReader()
    run(args.server, cams[args.camera], reader)


if __name__ == "__main__":
    main()
