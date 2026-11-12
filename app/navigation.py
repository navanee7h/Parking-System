"""Walking routes: shortest paths on each floor's raster + lifts/stairs between floors."""
from __future__ import annotations

import heapq
import math
from functools import lru_cache

import cv2
import numpy as np

from .lot import Floor, Lot, Point

SQRT2 = math.sqrt(2)
LIFT_M, LIFT_PER_LEVEL_M = 20.0, 3.0   # waiting for a lift "costs" ~20 m of walking
STAIRS_PER_LEVEL_M = 7.0


class FloorGraph:
    def __init__(self, floor: Floor):
        self.floor = floor
        free = (~floor.blocked).astype(np.uint8)
        # 4-connectivity: matches the router, which never cuts diagonally past a wall corner
        n, labels = cv2.connectedComponents(free, connectivity=4)
        sizes = np.bincount(labels[free > 0].ravel(), minlength=n)
        sizes[0] = 0
        self.main = labels == int(np.argmax(sizes))
        self.main_cells = np.argwhere(self.main)
        dist = cv2.distanceTransform(free, cv2.DIST_L2, 3)
        cost = 1.0 + floor.wall_penalty * np.clip(1.0 - dist / 3.0, 0, 1)
        self.rows, self.cols = free.shape
        self.cost = cost.ravel().tolist()
        self.open = self.main.ravel().tolist()

    def snap(self, x: float, y: float) -> int:
        """Nearest walkable cell (in the main connected area) to a plan coordinate."""
        r, c = self.floor.to_cell(x, y)
        if not self.main[r, c]:
            d = (self.main_cells[:, 0] - r) ** 2 + (self.main_cells[:, 1] - c) ** 2
            r, c = self.main_cells[int(np.argmin(d))]
        return int(r) * self.cols + int(c)

    @lru_cache(maxsize=512)
    def dijkstra(self, src: int) -> tuple[list[float], list[int]]:
        rows, cols, cost, ok = self.rows, self.cols, self.cost, self.open
        dist = [math.inf] * (rows * cols)
        parent = [-1] * (rows * cols)
        dist[src] = 0.0
        heap = [(0.0, src)]
        pop, push = heapq.heappop, heapq.heappush
        while heap:
            d, u = pop(heap)
            if d > dist[u]:
                continue
            r, c = divmod(u, cols)
            up, down, left, right = r > 0, r < rows - 1, c > 0, c < cols - 1
            cu = cost[u]
            for ok_dir, v, step in (
                (up, u - cols, 1.0), (down, u + cols, 1.0), (left, u - 1, 1.0), (right, u + 1, 1.0),
                (up and left and ok[u - cols] and ok[u - 1], u - cols - 1, SQRT2),
                (up and right and ok[u - cols] and ok[u + 1], u - cols + 1, SQRT2),
                (down and left and ok[u + cols] and ok[u - 1], u + cols - 1, SQRT2),
                (down and right and ok[u + cols] and ok[u + 1], u + cols + 1, SQRT2),
            ):
                if ok_dir and ok[v]:
                    nd = d + step * (cu + cost[v]) * 0.5
                    if nd < dist[v]:
                        dist[v] = nd
                        parent[v] = u
                        push(heap, (nd, v))
        return dist, parent

    def path(self, src: int, dst: int) -> list[int]:
        """Cells from src to dst (dijkstra is run from src and cached)."""
        _, parent = self.dijkstra(src)
        out = [dst]
        while out[-1] != src:
            p = parent[out[-1]]
            if p < 0:
                raise ValueError("no walkable route")
            out.append(p)
        return out[::-1]

    def xy(self, cell: int) -> tuple[float, float]:
        return self.floor.to_xy(divmod(cell, self.cols))


def _rdp(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-9
    i_max, d_max = 0, -1.0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / norm
        if d > d_max:
            i_max, d_max = i, d
    if d_max <= eps:
        return [pts[0], pts[-1]]
    return _rdp(pts[: i_max + 1], eps)[:-1] + _rdp(pts[i_max:], eps)


def _turn(a: tuple[float, float], b: tuple[float, float]) -> tuple[str, float]:
    """Turn from heading a to heading b. Plan y grows downward."""
    ang = math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))
    side = "right" if ang > 0 else "left"
    return side, abs(ang)


def _segments(pts, m_per_unit, min_m=4.0):
    """Path -> [heading, metres] legs; tiny wiggles merged, last (into the stall) kept."""
    raw = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        length = math.hypot(x2 - x1, y2 - y1) * m_per_unit
        if length > 1e-6:
            raw.append([((x2 - x1), (y2 - y1)), length])
    if not raw:
        return raw
    last = raw.pop() if len(raw) > 1 and raw[-1][1] < 6 else None
    segs: list[list] = []
    for h, length in raw:
        if segs and (_turn(segs[-1][0], h)[1] < 25 or length < min_m):
            # keep the heading of whichever part is longer
            if length > segs[-1][1]:
                segs[-1][0] = h
            segs[-1][1] += length
            continue
        segs.append([h, length])
    if last:
        segs.append(last)
    return segs


def _walk_steps(segs, start_phrase: str) -> list[str]:
    steps = []
    for i, (h, m) in enumerate(segs):
        dist = f"about {max(1, round(m))} m"
        if i == 0:
            steps.append(f"{start_phrase} {dist}.")
            continue
        side, ang = _turn(segs[i - 1][0], h)
        verb = "Bear" if ang < 60 else "Turn" if ang < 150 else "Turn around"
        steps.append(f"{verb} {side if ang < 150 else ''} and walk {dist}.".replace("  ", " ")
                     .replace("Turn around left", "Turn around").replace("Turn around right", "Turn around"))
    return steps


class Router:
    def __init__(self, lot: Lot):
        self.lot = lot
        self.graphs = {fid: FloorGraph(f) for fid, f in lot.floors.items()}
        self.m_per_cell = {fid: lot.meters_per_unit * f.cell for fid, f in lot.floors.items()}

    # -- helpers
    def _cell(self, floor: str, x: float, y: float) -> int:
        return self.graphs[floor].snap(x, y)

    def _vertical_m(self, p: Point, levels: int) -> float:
        if p.kind == "lift":
            return LIFT_M + LIFT_PER_LEVEL_M * levels
        return STAIRS_PER_LEVEL_M * levels

    def _connectors(self, a: str, b: str) -> list[tuple[Point, Point]]:
        """Pairs (point on floor a, point on floor b) of the same lift shaft / stairwell."""
        on_a = {p.link: p for p in self.lot.points.values() if p.floor == a and p.link}
        return [(on_a[p.link], p) for p in self.lot.points.values()
                if p.floor == b and p.link in on_a]

    def _leg(self, floor: str, start_xy, src: int, dst: int, end_xy, start_phrase: str):
        g = self.graphs[floor]
        cells = g.path(src, dst)
        # simplify the walk itself; keep the step out of the lobby and into the stall exact
        walk = _rdp([g.xy(c) for c in cells], eps=max(g.floor.cell * 1.5, 2.0 / self.lot.meters_per_unit))
        simple = [start_xy] + walk + [end_xy]
        segs = _segments(simple, self.lot.meters_per_unit)
        metres = sum(s[1] for s in segs)
        return {"floor": floor, "path": [[round(x, 1), round(y, 1)] for x, y in simple]}, \
            _walk_steps(segs, start_phrase), metres, segs

    # -- public
    def route(self, from_id: str, slot_id: str, lifts_only: bool = False) -> dict:
        lot = self.lot
        p, s = lot.points[from_id], lot.slots[slot_id]
        start_phrase = {"lift": "Leave the lift lobby and walk", "stairs": "Leave the stairwell and walk"
                        }.get(p.kind, "Walk")
        src = self._cell(p.floor, p.x, p.y)
        dst = self._cell(s.floor, s.x, s.y)

        if p.floor == s.floor:
            leg, steps, metres, segs = self._leg(p.floor, (p.x, p.y), src, dst, (s.x, s.y), start_phrase)
            legs, total = [leg], metres
        else:
            ga, gb = self.graphs[p.floor], self.graphs[s.floor]
            dist_a, _ = ga.dijkstra(src)
            dist_b, _ = gb.dijkstra(dst)   # from the slot: one run covers every lift on that floor
            levels = abs(lot.floors[s.floor].level - lot.floors[p.floor].level)
            best = None
            for ca, cb in self._connectors(p.floor, s.floor):
                if lifts_only and ca.kind != "lift":
                    continue
                ia, ib = self._cell(p.floor, ca.x, ca.y), self._cell(s.floor, cb.x, cb.y)
                cost = (dist_a[ia] * self.m_per_cell[p.floor] + self._vertical_m(ca, levels)
                        + dist_b[ib] * self.m_per_cell[s.floor])
                if best is None or cost < best[0]:
                    best = (cost, ca, cb, ia, ib)
            if best is None or math.isinf(best[0]):
                raise ValueError(f"no {'lift' if lifts_only else 'lift or stairs'} connects {p.floor} and {s.floor}")
            _, ca, cb, ia, ib = best
            leg1, steps1, m1, _ = self._leg(p.floor, (p.x, p.y), src, ia, (ca.x, ca.y), start_phrase)
            what = "lift" if ca.kind == "lift" else "stairs"
            updown = "up" if lot.floors[s.floor].level > lot.floors[p.floor].level else "down"
            dest_name = lot.floors[s.floor].name
            if p.id == ca.id:
                steps1 = []
            elif m1 < 12:
                steps1 = [f"Go to {what} {ca.id}, a few metres away."]
            hop = f"Take lift {ca.id} {updown} to {dest_name}." if what == "lift" else \
                f"Take stairs {ca.id} {updown} {levels} level{'s' if levels > 1 else ''} to {dest_name}."
            leg2, steps2, m2, segs = self._leg(s.floor, (cb.x, cb.y), ib, dst, (s.x, s.y),
                                               f"Leave the {what} at {cb.id} and walk")
            legs, total = [leg1, leg2], m1 + m2
            steps = steps1 + [hop] + steps2

        # finish: "Slot X is on your left" if the last bit is a short turn into the stall
        if len(segs) >= 2 and segs[-1][1] < 6:
            side, ang = _turn(segs[-2][0], segs[-1][0])
            steps[-1] = f"Your car is in slot {slot_id}, on your {side}." if ang < 150 else \
                f"Your car is in slot {slot_id}, just behind you."
        else:
            steps.append(f"You've reached slot {slot_id}.")
        return {"from": from_id, "slot": slot_id, "floor": s.floor,
                "distance_m": round(total, 1), "legs": legs, "steps": steps}

    def nearest_free(self, from_id: str, free_slots: list[str]) -> dict | None:
        """Closest free slot: same floor first (by walking distance), then nearest levels."""
        lot = self.lot
        p = lot.points[from_id]
        by_floor: dict[str, list[str]] = {}
        for sid in free_slots:
            by_floor.setdefault(lot.slots[sid].floor, []).append(sid)
        order = sorted(by_floor, key=lambda f: abs(lot.floors[f].level - lot.floors[p.floor].level))
        for fid in order:
            g = self.graphs[fid]
            dist, _ = g.dijkstra(g.snap(p.x, p.y))
            best = min(by_floor[fid], key=lambda sid: dist[g.snap(lot.slots[sid].x, lot.slots[sid].y)])
            if not math.isinf(dist[g.snap(lot.slots[best].x, lot.slots[best].y)]):
                if fid == p.floor:
                    return self.route(from_id, best)
                return {"from": from_id, "slot": best, "floor": fid, "legs": [], "steps": [],
                        "distance_m": None}
        return None
