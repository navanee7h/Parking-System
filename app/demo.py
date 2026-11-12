"""Fill the lot with fake cars so the app can be tried without cameras."""
from __future__ import annotations

import random

from .db import Store
from .lot import Lot

STATES = ["KA", "TN", "MH", "KL", "DL", "AP", "TS"]
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def random_plate(rng: random.Random) -> str:
    return (rng.choice(STATES) + f"{rng.randint(1, 60):02d}"
            + "".join(rng.choice(LETTERS) for _ in range(2)) + f"{rng.randint(1, 9999):04d}")


def hide_some(plate: str, rng: random.Random) -> str:
    """Simulate a plate the camera could only partly read."""
    kind = rng.random()
    if kind < 0.5:  # a couple of unreadable characters
        chars = list(plate)
        for i in rng.sample(range(len(chars)), 2):
            chars[i] = "?"
        return "".join(chars)
    if kind < 0.8:  # left part hidden by a pillar / other car
        return plate[4:]
    return plate[:-3] + "???"  # right part hidden


def seed(store: Store, lot: Lot, fill: float = 0.6, seed_value: int = 7) -> list[tuple[str, str]]:
    rng = random.Random(seed_value)
    seeded = []
    fixed = {"A05": "KA05MH1234", "C11": "TN09AB4521", "D17": "KL07?Z88?1"}
    for sid in lot.slots:
        if sid in fixed or rng.random() < fill:
            plate = fixed.get(sid) or random_plate(rng)
            conf = 0.95
            if sid not in fixed and rng.random() < 0.2:
                plate, conf = hide_some(plate, rng), 0.55
            store.set_occupancy(sid, True, "DEMO")
            store.set_plate(sid, plate, conf, "DEMO")
            seeded.append((sid, plate))
    return seeded
