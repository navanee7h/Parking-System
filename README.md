# Parking System

Find your car in a mall car park using the CCTV cameras that are already there.

1. **CCTV cameras** watch the parking slots. For every slot the system works out whether it is
   **occupied or free**, and reads the **number plate** of the car parked in it.
2. A visitor coming back from the mall **scans the QR code** at the entrance. The QR tells the
   site where they're standing (`/?kiosk=K1`).
3. They **type their number plate**, and the site shows the **slot on a map**, the **walking route**
   from where they're standing, and turn-by-turn directions.
4. **Partial plates work both ways:**
   - the camera only saw part of the plate (dirt, a pillar, a bad angle): unreadable characters are
     stored as `?` (e.g. `KL07?Z88?1`), or only the visible part is kept (`MH4321`);
   - the visitor only remembers part of it (`1234`, `KA05`).
   In both cases the site shows a **"Did you mean…?" list of suggestions** ranked by match score.
5. A live **availability board** (`/board`) shows free/occupied slots and the nearest free slot
   to the vehicle gate, for display screens at the entry.

```
 CCTV / NVR ──► vision worker (OpenCV + OCR) ──POST──► FastAPI server ──► SQLite
                  • slot occupancy                       • /api/search   (fuzzy plate match)
                  • plate reading                        • /api/route    (A* walking route)
                  • merge reads over time                • /api/slots, /api/nearest-free
                                                         • web pages: /  and  /board
 Visitor phone ──scan QR──► /?kiosk=K1 ──type plate──► suggestions ──► map + directions
```

## Quick start (demo mode, no cameras needed)

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

- Find-my-car page: <http://localhost:8000/?kiosk=K1>  (try `KA05MH1234`, `4521`, `KL07AZ8851`)
- Availability board: <http://localhost:8000/board>

Demo mode (`PARKING_DEMO=1`, the default) fills the empty lot with fake cars, some with
partly-read plates. Set `PARKING_DEMO=0` in production.

Run the tests:

```bash
pytest -q
```

## Setting it up for a real car park

### 1. Draw the lot — `config/lot.json`
The lot is a character grid; it drives the map **and** the route finding.

| char | meaning |
|---|---|
| `#` | wall / not walkable |
| `.` | driveway / walkway |
| `A`–`Z` | a parking slot. IDs are the letter + position in that row: `A01`, `A02`, … |
| `G`, `1`–`9` | named points (vehicle gate, QR kiosks), defined under `points` |

`cell_meters` sets how many metres one cell is (used for walking distances).

### 2. Map cameras to slots
For each camera, list its stream URL and a polygon (pixel coordinates in that camera's image)
for every slot it can see. Optionally save a photo of the **empty** lot as
`reference_image`; occupancy detection is much more reliable with it.

### 3. Run a vision worker per camera
```bash
pip install easyocr            # plate OCR
export PARKING_API_KEY=change-me   # same value on the server
python -m app.vision.worker --server http://SERVER:8000 --camera CAM-A-WEST
```
The worker samples a frame every few seconds, then:
- **occupancy**: compares each slot polygon to the empty reference + edge density, and only
  flips a slot after it's looked the same for 3 frames (people walking past don't count);
- **plates**: reads plates, assigns each to the slot polygon it's in, and **merges reads over
  time** so a `?` in one frame gets filled in by a later frame that saw that character;
- pushes changes to `POST /api/ingest/occupancy` and `POST /api/ingest/plate` (header `X-API-Key`).

The `PlateReader` interface in `app/vision/anpr.py` is pluggable. EasyOCR works for a start;
for production accuracy use a dedicated plate detector (e.g. a YOLO plate model) + OCR, or
your NVR's built-in ANPR, and post its results to the same ingest endpoints.

### 4. Print the QR codes
```bash
python scripts/make_qr.py --base-url https://parking.yourmall.com
```
Creates `qr/K1.png`, `qr/K2.png`, … Put each one at the matching location on the map.

## How partial matching works (`app/plate_matcher.py`)
- Input is normalised: `ka-05 mh 1234` → `KA05MH1234`; `*` or `_` can be typed as a wildcard.
- Score = weighted edit distance with **free gaps at either end**, so a fragment can match anywhere
  in a full plate (and a full query can match a fragment the camera stored).
- `?` matches anything at a small cost.
- Characters OCR mixes up (`0/O/D`, `1/I/L`, `8/B`, `5/S`, `2/Z`, …) are cheap substitutions.
- Results are lightly re-ranked by how confident the camera read was. An exact match is shown
  first and opens the route straight away; otherwise the top 5 suggestions are listed.

## API
| method | path | what |
|---|---|---|
| GET | `/api/lot` | grid, slots, points (for drawing the map) |
| GET | `/api/slots` | free / occupied counts and per-slot status (no plates) |
| GET | `/api/search?q=KA05` | plate suggestions with slot + match score |
| GET | `/api/route?from=K1&slot=A05` | walking path, distance and directions |
| GET | `/api/nearest-free?from=GATE` | nearest free slot + route |
| POST | `/api/ingest/occupancy` | `{camera_id, slots: {A01: true}}` (needs `X-API-Key`) |
| POST | `/api/ingest/plate` | `{camera_id, slot_id, plate, confidence}` (needs `X-API-Key`) |

Config via environment: `PARKING_LOT_CONFIG`, `PARKING_DB`, `PARKING_API_KEY`, `PARKING_DEMO`.

## Privacy
Plates are personal data. The public status endpoint never returns plates; search needs at least
3 known characters and returns at most 5 results; a plate is deleted as soon as the slot becomes
free. Before going live you should also add rate limiting on `/api/search`, and consider showing
masked plates in suggestions, depending on local rules.

## Roadmap ideas
- Multi-level car parks (one grid per level + lift/stair links in routing)
- Car photo thumbnail in suggestions so people can recognise their car
- "Text me my slot" / save to phone
- Entry/exit gate ANPR for parking duration and payment
