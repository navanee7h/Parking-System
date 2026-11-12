"""Fuzzy / partial number-plate matching.

Two kinds of "partial" are handled:

1. The *camera* only saw part of the plate (dirt, another car, angle). The vision
   pipeline stores unreadable characters as '?', e.g. ``KA05M?12?4``, or stores only
   the visible fragment, e.g. ``MH1234``.
2. The *visitor* only remembers / types part of it, e.g. ``1234`` or ``ka 05``.

Scoring is a weighted edit distance with:
  * '?' (in either string) matching any character at a small cost,
  * cheap substitutions for characters OCR commonly confuses (0/O, 1/I, 8/B, ...),
  * free leading/trailing gaps in the longer string, so a fragment can match
    anywhere inside a full plate (semi-global alignment).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

WILDCARD = "?"

_CONFUSABLE_GROUPS = ["0ODQU", "1IL7T", "2Z", "5S", "8B", "6G", "4A", "MN", "VY", "UV", "CG", "EF"]
_CONFUSE: dict[tuple[str, str], float] = {}
for grp in _CONFUSABLE_GROUPS:
    for a in grp:
        for b in grp:
            if a != b:
                _CONFUSE[(a, b)] = 0.35

SUB_COST = 1.0
GAP_COST = 1.0
WILDCARD_COST = 0.15


def normalize(text: str) -> str:
    """Uppercase, keep A-Z 0-9 and '?' ('*', '_' and '.' are typed wildcards)."""
    text = text.upper().replace("*", WILDCARD).replace("_", WILDCARD)
    return re.sub(r"[^A-Z0-9?]", "", text)


def _sub(a: str, b: str) -> float:
    if a == b:
        return 0.0
    if a == WILDCARD or b == WILDCARD:
        return WILDCARD_COST
    return _CONFUSE.get((a, b), SUB_COST)


def semiglobal_cost(short: str, long: str) -> float:
    """Cost of aligning all of `short` to any substring of `long`."""
    n, m = len(short), len(long)
    prev = [0.0] * (m + 1)  # free leading gap in `long`
    for i in range(1, n + 1):
        cur = [prev[0] + GAP_COST] + [0.0] * m
        for j in range(1, m + 1):
            cur[j] = min(
                prev[j - 1] + _sub(short[i - 1], long[j - 1]),
                prev[j] + GAP_COST,       # char in short not in long
                cur[j - 1] + GAP_COST,    # char in long not in short
            )
        prev = cur
    return min(prev)  # free trailing gap in `long`


def similarity(query: str, plate: str) -> float:
    """0..1 score; 1.0 means an exact, complete match."""
    q, p = normalize(query), normalize(plate)
    if not q or not p:
        return 0.0
    if q == p:
        return 1.0
    short, long = (q, p) if len(q) <= len(p) else (p, q)
    cost = semiglobal_cost(short, long)
    core = max(0.0, 1.0 - cost / len(short))
    coverage = len(short) / len(long)
    # unknown chars in the *query* say nothing about the plate, so they don't count
    known = sum(ch != WILDCARD for ch in short) / len(short)
    return round(core * (0.6 + 0.4 * coverage) * (0.5 + 0.5 * known), 4)


@dataclass
class Match:
    plate: str
    slot_id: str
    score: float
    exact: bool
    read_confidence: float
    updated_at: str | None = None


def search(query: str, vehicles: list[dict], limit: int = 5, min_score: float = 0.45) -> list[Match]:
    """`vehicles`: dicts with plate, slot_id, plate_conf, updated_at."""
    q = normalize(query)
    if len(q.replace(WILDCARD, "")) < 3:
        return []
    out: list[Match] = []
    for v in vehicles:
        s = similarity(q, v["plate"])
        # a shaky camera read slightly lowers the ranking but never hides the car
        ranked = s * (0.85 + 0.15 * float(v.get("plate_conf") or 0))
        if s >= min_score:
            out.append(Match(v["plate"], v["slot_id"], round(ranked, 4), s == 1.0,
                             float(v.get("plate_conf") or 0), v.get("updated_at")))
    out.sort(key=lambda m: (m.exact, m.score), reverse=True)
    return out[:limit]
