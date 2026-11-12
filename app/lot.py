"""Parking-lot model: floors, slots and named points (kiosks, lifts, stairs, gates).

Two config formats load into the same model:

* ``"format": "grid"``      - a hand-drawn character grid (see config/sample_grid_lot.json)
* ``"format": "floorplan"`` - floors imported from a CAD PDF by scripts/import_floorplan_pdf.py

Every floor also gets a *walkable raster* (``blocked``) used for route finding.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Slot:
    id: str
    floor: str
    x: float
    y: float


@dataclass(frozen=True)
class Point:
    id: str
    name: str
    kind: str          # kiosk | lift | stairs | gate
    floor: str
    x: float
    y: float
    link: str | None = None   # same value on several floors = one lift shaft / stairwell


@dataclass
class Floor:
    id: str
    name: str
    level: int
    bounds: tuple[float, float, float, float]   # x0, y0, x1, y1 in plan units
    cell: float                                  # routing raster cell size in plan units
    blocked: np.ndarray = field(repr=False)      # bool [rows, cols]; True = can't walk
    drawing: dict = field(default_factory=dict, repr=False)  # styles/shapes/texts for the map
    marker: tuple[float, float] = (16.0, 8.0)    # slot marker size on the map
    wall_penalty: float = 2.0                    # prefer the middle of aisles

    def to_cell(self, x: float, y: float) -> tuple[int, int]:
        r = int((y - self.bounds[1]) / self.cell)
        c = int((x - self.bounds[0]) / self.cell)
        return (min(max(r, 0), self.blocked.shape[0] - 1), min(max(c, 0), self.blocked.shape[1] - 1))

    def to_xy(self, rc: tuple[int, int]) -> tuple[float, float]:
        return (round(self.bounds[0] + (rc[1] + 0.5) * self.cell, 1),
                round(self.bounds[1] + (rc[0] + 0.5) * self.cell, 1))

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "level": self.level,
                "bounds": list(self.bounds), "marker": list(self.marker)}


@dataclass
class Lot:
    name: str
    meters_per_unit: float
    floors: dict[str, Floor]
    slots: dict[str, Slot]
    points: dict[str, Point]
    cameras: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "meters_per_unit": self.meters_per_unit,
            "floors": [f.summary() for f in sorted(self.floors.values(), key=lambda f: f.level)],
            "slots": [s.__dict__ for s in self.slots.values()],
            "points": [p.__dict__ for p in self.points.values()],
        }


# ---------------------------------------------------------------- grid format

def _load_grid(cfg: dict) -> Lot:
    grid: list[str] = cfg["grid"]
    if len({len(r) for r in grid}) != 1:
        raise ValueError("all grid rows must have the same length")
    rows, cols = len(grid), len(grid[0])
    point_defs = cfg.get("points", {})
    blocked = np.ones((rows, cols), bool)
    slots: dict[str, Slot] = {}
    points: dict[str, Point] = {}
    counters: dict[str, int] = {}
    walls = []
    for r, line in enumerate(grid):
        for c, ch in enumerate(line):
            if ch == "#":
                walls.append({"s": 0, "p": [c, r, c + 1, r, c + 1, r + 1, c, r + 1], "z": 1})
            elif ch == "." or ch in point_defs:
                blocked[r, c] = False
                if ch in point_defs:
                    d = point_defs[ch]
                    points[d["id"]] = Point(d["id"], d["name"], d.get("kind", "kiosk"), "1", c + 0.5, r + 0.5)
            elif ch.isalpha() and ch.isupper():
                counters[ch] = counters.get(ch, 0) + 1
                sid = f"{ch}{counters[ch]:02d}"
                slots[sid] = Slot(sid, "1", c + 0.5, r + 0.5)
    drawing = {"styles": [{"stroke": None, "width": 0, "fill": "wall"}], "shapes": walls, "texts": []}
    floor = Floor("1", cfg.get("floor_name", "Ground"), 1, (0, 0, cols, rows), 1.0, blocked,
                  drawing, marker=(0.8, 0.8), wall_penalty=0.0)
    return Lot(cfg.get("name", "Parking"), float(cfg.get("cell_meters", 2.5)),
               {"1": floor}, slots, points, cfg.get("cameras", []))


# ----------------------------------------------------------- floorplan format

def _rasterize(f: dict, cell: float) -> np.ndarray:
    x0, y0, x1, y1 = f["bounds"]
    rows, cols = int((y1 - y0) / cell) + 1, int((x1 - x0) / cell) + 1
    img = np.zeros((rows, cols), np.uint8)

    def px(flat):
        a = np.array(flat, np.float32).reshape(-1, 2)
        return np.round(np.column_stack(((a[:, 0] - x0) / cell, (a[:, 1] - y0) / cell))).astype(np.int32)

    styles = f["styles"]
    for sh in f["shapes"]:
        st = styles[sh["s"]]
        pts = px(sh["p"])
        if st.get("fill") and sh.get("z"):
            cv2.fillPoly(img, [pts], 255)
        # 4-connected lines so diagonal moves can't slip through a wall
        cv2.polylines(img, [pts], bool(sh.get("z")), 255, 1, lineType=4)
    inside = np.zeros_like(img)
    cv2.fillPoly(inside, [px(f["outline"])], 255)
    return (img > 0) | (inside == 0)


def _load_floorplan(cfg: dict, base: Path) -> Lot:
    cell = float(cfg.get("cell", 3.0))
    floors = {}
    for f in cfg["floors"]:
        drawing = {k: f[k] for k in ("styles", "shapes", "texts")}
        floors[f["id"]] = Floor(f["id"], f["name"], int(f["level"]), tuple(f["bounds"]), cell,
                                _rasterize(f, cell), drawing, marker=tuple(f.get("marker", (17, 8))))
    slots = {s["id"]: Slot(s["id"], s["floor"], s["x"], s["y"]) for s in cfg["slots"]}
    points = {p["id"]: Point(p["id"], p["name"], p["kind"], p["floor"], p["x"], p["y"], p.get("link"))
              for p in cfg["points"]}
    return Lot(cfg.get("name", "Parking"), float(cfg["meters_per_unit"]), floors, slots, points,
               cfg.get("cameras", []))


def load_lot(path: str | Path) -> Lot:
    path = Path(path)
    cfg = json.loads(path.read_text())
    fmt = cfg.get("format", "grid")
    if fmt == "grid":
        return _load_grid(cfg)
    if fmt == "floorplan":
        return _load_floorplan(cfg, path.parent)
    raise ValueError(f"unknown lot format {fmt!r}")
