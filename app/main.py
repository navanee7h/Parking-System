"""FastAPI server: car finder, live availability and camera ingestion."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import demo, navigation, plate_matcher
from .db import Store
from .lot import load_lot

ROOT = Path(__file__).resolve().parent.parent
LOT = load_lot(os.getenv("PARKING_LOT_CONFIG", ROOT / "config" / "lot.json"))
API_KEY = os.getenv("PARKING_API_KEY", "dev-key")
store = Store(os.getenv("PARKING_DB", str(ROOT / "parking.db")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.ensure_slots(LOT.slots)
    if os.getenv("PARKING_DEMO", "1") == "1" and store.is_empty():
        demo.seed(store, LOT)
    yield


app = FastAPI(title="Parking System", lifespan=lifespan)


# ---------- visitor-facing ----------

@app.get("/api/lot")
def get_lot():
    return LOT.to_dict()


@app.get("/api/slots")
def get_slots():
    rows = store.slots()
    free = [r["slot_id"] for r in rows if not r["occupied"]]
    # never expose plates on the public status endpoint
    return {
        "total": len(rows), "free": len(free), "occupied": len(rows) - len(free),
        "slots": [{"slot_id": r["slot_id"], "occupied": bool(r["occupied"])} for r in rows],
    }


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=20), limit: int = Query(5, ge=1, le=10)):
    matches = plate_matcher.search(q, store.vehicles(), limit=limit)
    return {
        "query": plate_matcher.normalize(q),
        "exact": bool(matches and matches[0].exact),
        "results": [m.__dict__ for m in matches],
    }


@app.get("/api/route")
def get_route(slot: str, from_: str = Query("K1", alias="from")):
    if slot not in LOT.slots:
        raise HTTPException(404, f"unknown slot {slot}")
    if from_ not in LOT.points:
        raise HTTPException(404, f"unknown location {from_}")
    return navigation.route(LOT, from_, slot)


@app.get("/api/nearest-free")
def nearest_free(from_: str = Query("GATE", alias="from")):
    if from_ not in LOT.points:
        raise HTTPException(404, f"unknown location {from_}")
    free = [r["slot_id"] for r in store.slots() if not r["occupied"]]
    best = None
    for sid in free:
        try:
            r = navigation.route(LOT, from_, sid)
        except ValueError:
            continue
        if best is None or r["distance_m"] < best["distance_m"]:
            best = r
    if best is None:
        raise HTTPException(404, "parking is full")
    return best


# ---------- camera ingestion ----------

class OccupancyIn(BaseModel):
    camera_id: str
    slots: dict[str, bool]


class PlateIn(BaseModel):
    camera_id: str
    slot_id: str
    plate: str = Field(min_length=1, max_length=16)
    confidence: float = Field(ge=0, le=1)


def _check_key(key: str | None):
    if key != API_KEY:
        raise HTTPException(401, "bad API key")


@app.post("/api/ingest/occupancy")
def ingest_occupancy(body: OccupancyIn, x_api_key: str | None = Header(None)):
    _check_key(x_api_key)
    for sid, occ in body.slots.items():
        if sid in LOT.slots:
            store.set_occupancy(sid, occ, body.camera_id)
    return {"ok": True}


@app.post("/api/ingest/plate")
def ingest_plate(body: PlateIn, x_api_key: str | None = Header(None)):
    _check_key(x_api_key)
    if body.slot_id not in LOT.slots:
        raise HTTPException(404, f"unknown slot {body.slot_id}")
    plate = plate_matcher.normalize(body.plate)
    if not plate:
        raise HTTPException(422, "empty plate")
    store.set_plate(body.slot_id, plate, body.confidence, body.camera_id)
    return {"ok": True, "plate": plate}


# ---------- pages ----------

STATIC = ROOT / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/board")
def board():
    return FileResponse(STATIC / "board.html")
