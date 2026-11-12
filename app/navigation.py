"""A* path-finding on the lot grid plus human-readable walking directions."""
from __future__ import annotations

import heapq

from .lot import NEIGHBOURS, Lot

Cell = tuple[int, int]


def astar(lot: Lot, start: Cell, goal: Cell) -> list[Cell] | None:
    def h(a: Cell) -> int:
        return abs(a[0] - goal[0]) + abs(a[1] - goal[1])

    open_heap: list[tuple[int, int, Cell]] = [(h(start), 0, start)]
    came_from: dict[Cell, Cell] = {}
    g = {start: 0}
    while open_heap:
        _, cost, cur = heapq.heappop(open_heap)
        if cur == goal:
            path = [cur]
            while cur in came_from:
                cur = came_from[cur]
                path.append(cur)
            return path[::-1]
        if cost > g.get(cur, 1 << 30):
            continue
        for dr, dc in NEIGHBOURS:
            nxt = (cur[0] + dr, cur[1] + dc)
            if not lot.walkable(*nxt):
                continue
            # tiny penalty for changing direction -> fewer, straighter turns
            turn = 0
            if cur in came_from:
                prev = came_from[cur]
                if (cur[0] - prev[0], cur[1] - prev[1]) != (dr, dc):
                    turn = 1
            ng = cost + 10 + turn
            if ng < g.get(nxt, 1 << 30):
                g[nxt] = ng
                came_from[nxt] = cur
                heapq.heappush(open_heap, (ng + 10 * h(nxt), ng, nxt))
    return None


def _turn(h1: Cell, h2: Cell) -> str:
    # screen coords: x = col, y = row (y grows downward)
    cross = h1[1] * h2[0] - h1[0] * h2[1]
    if cross > 0:
        return "right"
    if cross < 0:
        return "left"
    return "around" if h1 != h2 else "straight"


def directions(lot: Lot, path: list[Cell], slot_cell: Cell, slot_id: str) -> list[str]:
    if len(path) < 2:
        return [f"Your car is right here in slot {slot_id}."]
    segments: list[tuple[Cell, int]] = []  # (heading, cells)
    for a, b in zip(path, path[1:]):
        hd = (b[0] - a[0], b[1] - a[1])
        if segments and segments[-1][0] == hd:
            segments[-1] = (hd, segments[-1][1] + 1)
        else:
            segments.append((hd, 1))

    steps: list[str] = []
    for i, (hd, n) in enumerate(segments):
        metres = round(n * lot.cell_meters)
        if i == 0:
            steps.append(f"Walk straight ahead for about {metres} m.")
        else:
            steps.append(f"Turn {_turn(segments[i - 1][0], hd)} and walk about {metres} m.")

    last_hd = segments[-1][0]
    end = path[-1]
    to_slot = (slot_cell[0] - end[0], slot_cell[1] - end[1])
    side = _turn(last_hd, to_slot)
    where = "straight ahead" if side == "straight" else f"on your {side}" if side != "around" else "behind you"
    steps.append(f"Your car is in slot {slot_id}, {where}.")
    return steps


def route(lot: Lot, from_point: str, slot_id: str) -> dict:
    p = lot.points[from_point]
    s = lot.slots[slot_id]
    path = astar(lot, (p.row, p.col), s.access)
    if path is None:
        raise ValueError(f"no walkable route from {from_point} to {slot_id}")
    return {
        "from": from_point,
        "slot": slot_id,
        "path": [list(c) for c in path] + [[s.row, s.col]],
        "distance_m": round((len(path) - 1) * lot.cell_meters, 1),
        "steps": directions(lot, path, (s.row, s.col), slot_id),
    }
