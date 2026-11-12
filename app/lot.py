"""Parking-lot layout: a character grid that drives both the map and navigation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

WALL = "#"
FLOOR = "."
NEIGHBOURS = ((-1, 0), (1, 0), (0, -1), (0, 1))


@dataclass(frozen=True)
class Slot:
    id: str
    row: int
    col: int
    access: tuple[int, int]  # walkable cell next to the slot where you "arrive"


@dataclass(frozen=True)
class Point:
    id: str
    name: str
    kind: str  # "kiosk" | "gate"
    row: int
    col: int


@dataclass
class Lot:
    name: str
    grid: list[str]
    cell_meters: float
    slots: dict[str, Slot] = field(default_factory=dict)
    points: dict[str, Point] = field(default_factory=dict)
    cameras: list[dict] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return len(self.grid)

    @property
    def cols(self) -> int:
        return len(self.grid[0])

    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def walkable(self, r: int, c: int) -> bool:
        if not self.in_bounds(r, c):
            return False
        ch = self.grid[r][c]
        return ch == FLOOR or ch == "G" or ch.isdigit()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "grid": self.grid,
            "cell_meters": self.cell_meters,
            "slots": [s.__dict__ for s in self.slots.values()],
            "points": [p.__dict__ for p in self.points.values()],
        }


def load_lot(path: str | Path) -> Lot:
    cfg = json.loads(Path(path).read_text())
    grid: list[str] = cfg["grid"]
    if len({len(r) for r in grid}) != 1:
        raise ValueError("all grid rows must have the same length")

    lot = Lot(name=cfg.get("name", "Parking"), grid=grid,
              cell_meters=float(cfg.get("cell_meters", 2.5)),
              cameras=cfg.get("cameras", []))
    point_defs = cfg.get("points", {})
    counters: dict[str, int] = {}

    for r, line in enumerate(grid):
        for c, ch in enumerate(line):
            if ch in point_defs:
                d = point_defs[ch]
                lot.points[d["id"]] = Point(d["id"], d["name"], d.get("kind", "kiosk"), r, c)
            elif ch.isalpha() and ch.isupper():
                counters[ch] = counters.get(ch, 0) + 1
                sid = f"{ch}{counters[ch]:02d}"
                access = next(((r + dr, c + dc) for dr, dc in NEIGHBOURS
                               if lot.walkable(r + dr, c + dc)), None)
                if access is None:
                    raise ValueError(f"slot {sid} at ({r},{c}) has no adjacent driveway")
                lot.slots[sid] = Slot(sid, r, c, access)
    return lot
