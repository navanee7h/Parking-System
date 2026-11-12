from pathlib import Path

import pytest

from app.lot import load_lot
from app.navigation import Router

CFG = Path(__file__).resolve().parent.parent / "config"
GRID = load_lot(CFG / "sample_grid_lot.json")
PS1 = load_lot(CFG / "ps1" / "lot.json")


@pytest.fixture(scope="module")
def grid_router():
    return Router(GRID)


@pytest.fixture(scope="module")
def ps1_router():
    return Router(PS1)


def test_grid_lot_parsed():
    assert len(GRID.slots) == 76
    assert {"GATE", "K1", "K2"} <= set(GRID.points)


def test_grid_route_reaches_every_slot(grid_router):
    for p in ("K1", "K2", "GATE"):
        for sid, s in GRID.slots.items():
            r = grid_router.route(p, sid)
            assert r["legs"][-1]["path"][-1] == [s.x, s.y]
            assert r["steps"][-1].startswith(("Your car is in slot " + sid, "You've reached slot " + sid))


def test_grid_side_of_car(grid_router):
    # from K1 walking west along the aisle, row A is to the north = on your right
    assert grid_router.route("K1", "A05")["steps"][-1] == "Your car is in slot A05, on your right."


def test_floorplan_import():
    assert len(PS1.floors) == 8
    assert len(PS1.slots) == 890
    assert {"V101", "V801", "S101", "ENTRY-1", "SKYBRIDGE-4"} <= set(PS1.points)
    assert PS1.points["V101"].link == PS1.points["V501"].link
    assert 0.13 < PS1.meters_per_unit < 0.14   # 1/32" = 1 ft


def test_floorplan_every_slot_reachable(ps1_router):
    for fid in PS1.floors:
        lift = next(p for p in PS1.points.values() if p.floor == fid and p.kind == "lift")
        for s in (s for s in PS1.slots.values() if s.floor == fid):
            r = ps1_router.route(lift.id, s.id)
            assert r["distance_m"] < 250, (lift.id, s.id, r["distance_m"])


def test_multi_floor_route_uses_lift(ps1_router):
    r = ps1_router.route("V102", "5-143")
    assert [leg["floor"] for leg in r["legs"]] == ["1", "5"]
    assert "Take lift V102 up to Level 5." in r["steps"]


def test_lifts_only(ps1_router):
    normal = ps1_router.route("SKYBRIDGE-4", "2-120")
    assert any("stairs" in s for s in normal["steps"])
    lifts = ps1_router.route("SKYBRIDGE-4", "2-120", lifts_only=True)
    assert not any("stairs" in s.lower() for s in lifts["steps"])
    assert any(s.startswith("Take lift") for s in lifts["steps"])


def test_nearest_free_prefers_same_floor(ps1_router):
    free = ["8-101", "1-150", "1-101"]
    r = ps1_router.nearest_free("ENTRY-1", free)
    assert r["floor"] == "1" and r["slot"] in ("1-150", "1-101")
    r = ps1_router.nearest_free("ENTRY-1", ["8-101", "3-120"])
    assert r["slot"] == "3-120"
