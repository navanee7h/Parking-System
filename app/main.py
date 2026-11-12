"""FastAPI server: car finder, live availability and camera ingestion."""
from __future__ import annotations

import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import demo, navigation, plate_matcher
from .db import Store
from .lot import load_lot

ROOT = Path(__file__).resolve().parent.parent
LOT = load_lot(os.getenv("PARKING_LOT_CONFIG", ROOT / "config" / "ps1" / "lot.json"))
ROUTER = navigation.Router(LOT)
API_KEY = os.getenv("PARKING_API_KEY", "dev-key")
store = Store(os.getenv("PARKING_DB", str(ROOT / "parking.db")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.ensure_slots(LOT.slots)
    if os.getenv("PARKING_DEMO", "1") == "1" and store.is_empty(LOT.slots):
        demo.seed(store, LOT)
    yield


app = FastAPI(title="Parking System", lifespan=lifespan)


# ---------- visitor-facing ----------

@app.get("/api/lot")
def get_lot():
    return LOT.to_dict()


@app.get("/api/floors/{floor_id}")
def get_floor_drawing(floor_id: str, response: Response):
    if floor_id not in LOT.floors:
        raise HTTPException(404, f"unknown floor {floor_id}")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return LOT.floors[floor_id].drawing


@app.get("/api/slots")
def get_slots():
    rows = store.slots()
    per_floor: dict[str, dict] = {f: {"free": 0, "total": 0} for f in LOT.floors}
    for r in rows:
        f = LOT.slots[r["slot_id"]].floor if r["slot_id"] in LOT.slots else None
        if f:
            per_floor[f]["total"] += 1
            per_floor[f]["free"] += 0 if r["occupied"] else 1
    free = sum(v["free"] for v in per_floor.values())
    total = sum(v["total"] for v in per_floor.values())
    # never expose plates on the public status endpoint
    return {
        "total": total, "free": free, "occupied": total - free, "floors": per_floor,
        "slots": [{"slot_id": r["slot_id"], "occupied": bool(r["occupied"])}
                  for r in rows if r["slot_id"] in LOT.slots],
    }


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=20), limit: int = Query(5, ge=1, le=10)):
    vehicles = [v for v in store.vehicles() if v["slot_id"] in LOT.slots]
    matches = plate_matcher.search(q, vehicles, limit=limit)
    results = []
    for m in matches:
        floor = LOT.floors[LOT.slots[m.slot_id].floor]
        results.append({**m.__dict__, "floor": floor.id, "floor_name": floor.name})
    return {"query": plate_matcher.normalize(q), "exact": bool(matches and matches[0].exact),
            "results": results}


@app.get("/api/route")
def get_route(slot: str, from_: str = Query(..., alias="from"), lifts_only: bool = False):
    if slot not in LOT.slots:
        raise HTTPException(404, f"unknown slot {slot}")
    if from_ not in LOT.points:
        raise HTTPException(404, f"unknown location {from_}")
    try:
        return ROUTER.route(from_, slot, lifts_only=lifts_only)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/nearest-free")
def nearest_free(from_: str = Query(..., alias="from")):
    if from_ not in LOT.points:
        raise HTTPException(404, f"unknown location {from_}")
    free = [r["slot_id"] for r in store.slots() if not r["occupied"] and r["slot_id"] in LOT.slots]
    best = ROUTER.nearest_free(from_, free)
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

# Windows can map .js to text/plain in the registry; browsers then refuse to run the page scripts
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


@app.middleware("http")
async def no_stale_pages(request: Request, call_next):
    """Make browsers re-check pages/scripts so an update never mixes old and new files."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in ("/", "/board"):
        response.headers["Cache-Control"] = "no-cache"
    if path.endswith(".js"):
        response.headers["Content-Type"] = "text/javascript; charset=utf-8"
    return response


STATIC = ROOT / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/board")
def board():
    return FileResponse(STATIC / "board.html")
