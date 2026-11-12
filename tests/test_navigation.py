from pathlib import Path

from app.lot import load_lot
from app.navigation import route

LOT = load_lot(Path(__file__).resolve().parent.parent / "config" / "lot.json")


def test_slots_parsed():
    assert len(LOT.slots) == 76
    assert LOT.slots["A01"].access == (2, 1)
    assert {"GATE", "K1", "K2"} <= set(LOT.points)


def test_route_reaches_every_slot_from_every_kiosk():
    for p in ("K1", "K2", "GATE"):
        for sid in LOT.slots:
            r = route(LOT, p, sid)
            assert r["path"][-1] == [LOT.slots[sid].row, LOT.slots[sid].col]
            for (r1, c1), (r2, c2) in zip(r["path"], r["path"][1:]):
                assert abs(r1 - r2) + abs(c1 - c2) == 1


def test_directions_mention_slot_and_side():
    r = route(LOT, "K1", "A05")
    assert r["steps"][-1].startswith("Your car is in slot A05")
    assert "right" in r["steps"][-1]  # walking west along row 2, row A is to the north -> right
