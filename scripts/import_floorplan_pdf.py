"""Turn a CAD floor-plan PDF (one floor per page) into a Parking System lot config.

    pip install pymupdf
    python scripts/import_floorplan_pdf.py plans.pdf --out config/ps1/lot.json --name "Parking Structure 1"

What it extracts from every page that has parking-slot labels:
  * the drawing (walls, stall lines, arrows...) as polylines -> map + walkable area
  * slot labels matching --slot-regex (default '1-143' style)  -> slot positions
  * lift / stair labels (default 'V101', 'S203')               -> QR kiosk points and
    vertical links between floors (V101, V201, V301... = the same lift shaft)
  * ENTRY / EXIT / SKYBRIDGE words                             -> named points
Scale comes from --feet-per-inch (the drawing scale, e.g. 1/32" = 1'-0" -> 32).
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np
import pymupdf


def flatten(item) -> tuple[list[tuple[float, float]], bool]:
    kind = item[0]
    if kind == "l":
        return [(item[1].x, item[1].y), (item[2].x, item[2].y)], False
    if kind == "re":
        r = item[1]
        return [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)], True
    if kind == "qu":
        q = item[1]
        return [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)], True
    if kind == "c":
        p0, c1, c2, p3 = item[1:5]
        pts = []
        for i in range(7):
            t = i / 6
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
            pts.append((a * p0.x + b * c1.x + c * c2.x + d * p3.x, a * p0.y + b * c1.y + c * c2.y + d * p3.y))
        return pts, False
    return [], False


def colour(c) -> str | None:
    if c is None:
        return None
    r, g, b = c
    if r > 0.8 and g < 0.3 and b < 0.3:
        return "accent"   # red symbols (lift access, wheelchair) -> themed accent colour
    if max(c) < 0.2:
        return "line"
    return "faint"


def ordinal_name(level: int) -> str:
    return f"Level {level}"


def import_page(page, args, slot_re, lift_re, stair_re):
    words = page.get_text("words")
    slots = [w for w in words if slot_re.fullmatch(w[4])]
    if not slots:
        return None
    level = int(slots[0][4].split("-")[0])

    # plan area = drawings near the slot labels (excludes title block / legend)
    sx0, sy0 = min(w[0] for w in slots), min(w[1] for w in slots)
    sx1, sy1 = max(w[2] for w in slots), max(w[3] for w in slots)
    m = args.margin
    near = pymupdf.Rect(sx0 - m, sy0 - m, sx1 + m, sy1 + m)
    drawings = [d for d in page.get_drawings() if near.contains(d["rect"])]
    bounds = pymupdf.Rect(sx0, sy0, sx1, sy1)
    for d in drawings:
        if colour(d.get("color")) == "line":
            bounds |= d["rect"]
    bounds = bounds & near
    bounds = pymupdf.Rect(bounds.x0 - 8, bounds.y0 - 8, bounds.x1 + 8, bounds.y1 + 8)

    styles: list[dict] = []
    style_ix: dict[tuple, int] = {}
    shapes = []
    hull_pts = []
    for d in drawings:
        stroke = colour(d.get("color"))
        fill = colour(d.get("fill"))
        key = (stroke, round(d.get("width") or 0, 2), fill)
        if key not in style_ix:
            style_ix[key] = len(styles)
            styles.append({"stroke": stroke, "width": key[1], "fill": fill})
        s = style_ix[key]
        cur: list[tuple[float, float]] = []
        for it in d["items"]:
            pts, closed = flatten(it)
            if not pts:
                continue
            if not closed and cur and math.dist(cur[-1], pts[0]) < 0.01:
                cur.extend(pts[1:])
                continue
            if cur:
                shapes.append({"s": s, "p": [round(v, 1) for xy in cur for v in xy]})
                cur = []
            if closed or fill:
                shapes.append({"s": s, "p": [round(v, 1) for xy in pts for v in xy], "z": 1})
            else:
                cur = list(pts)
            if stroke == "line":
                hull_pts.extend(pts)
        if cur:
            shapes.append({"s": s, "p": [round(v, 1) for xy in cur for v in xy]})

    hull = cv2.convexHull(np.array(hull_pts, np.float32)).reshape(-1, 2)
    outline = [round(float(v), 1) for xy in hull for v in xy]

    texts = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for sp in line["spans"]:
                t = sp["text"].strip()
                x, y = sp["origin"]
                if not t or slot_re.fullmatch(t) or not bounds.contains(pymupdf.Point(x, y)):
                    continue
                rot = round(math.degrees(math.atan2(line["dir"][1], line["dir"][0])))
                texts.append({"t": t, "x": round(x, 1), "y": round(y, 1),
                              "size": round(sp["size"], 1), "rot": rot})

    floor_id = str(level)
    floor = {"id": floor_id, "name": ordinal_name(level), "level": level,
             "bounds": [round(v, 1) for v in bounds], "outline": outline,
             "styles": styles, "shapes": shapes, "texts": texts}

    out_slots = [{"id": w[4], "floor": floor_id,
                  "x": round((w[0] + w[2]) / 2, 1), "y": round((w[1] + w[3]) / 2, 1)} for w in slots]

    points = []
    for w in words:
        cx, cy = round((w[0] + w[2]) / 2, 1), round((w[1] + w[3]) / 2, 1)
        if not bounds.contains(pymupdf.Point(cx, cy)):
            continue
        if (mm := lift_re.fullmatch(w[4])):
            points.append({"id": w[4], "name": f"{ordinal_name(level)} · Lift {w[4]}", "kind": "lift",
                           "floor": floor_id, "x": cx, "y": cy, "link": "lift-" + mm.group(2)})
        elif (mm := stair_re.fullmatch(w[4])):
            points.append({"id": w[4], "name": f"{ordinal_name(level)} · Stairs {w[4]}", "kind": "stairs",
                           "floor": floor_id, "x": cx, "y": cy, "link": "stairs-" + mm.group(2)})
        elif w[4] in ("ENTRY", "EXIT"):
            pid = f"{w[4]}-{floor_id}"
            if not any(p["id"] == pid for p in points):
                points.append({"id": pid, "name": f"{ordinal_name(level)} · Vehicle {w[4].lower()}",
                               "kind": "gate", "floor": floor_id, "x": cx, "y": cy})
        elif w[4] == "SKYBRIDGE":
            points.append({"id": f"SKYBRIDGE-{floor_id}", "name": f"{ordinal_name(level)} · Skybridge",
                           "kind": "kiosk", "floor": floor_id, "x": cx, "y": cy})
    return floor, out_slots, points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="Parking Structure")
    ap.add_argument("--feet-per-inch", type=float, default=32.0, help="drawing scale (1/32in = 1ft -> 32)")
    ap.add_argument("--slot-regex", default=r"\d-\d{3}")
    ap.add_argument("--lift-regex", default=r"V(\d)(\d\d)")
    ap.add_argument("--stair-regex", default=r"S(\d)(\d\d)")
    ap.add_argument("--margin", type=float, default=80.0, help="pts around slot labels that count as plan")
    ap.add_argument("--cell", type=float, default=3.0, help="routing grid size in PDF points")
    args = ap.parse_args()

    slot_re, lift_re, stair_re = (re.compile(args.slot_regex), re.compile(args.lift_regex),
                                  re.compile(args.stair_regex))
    floors, slots, points = [], [], []
    for page in pymupdf.open(args.pdf):
        res = import_page(page, args, slot_re, lift_re, stair_re)
        if res:
            floors.append(res[0]); slots += res[1]; points += res[2]
            print(f"{res[0]['name']}: {len(res[1])} slots, {len(res[2])} points, {len(res[0]['shapes'])} shapes")

    # the drawing may label two stalls the same; keep both, rename the later one
    seen: dict[str, int] = {}
    for sl in slots:
        n = seen.get(sl["id"], 0) + 1
        seen[sl["id"]] = n
        if n > 1:
            new = f"{sl['id']}-{n}"
            print(f"WARNING: slot {sl['id']} appears more than once (floor {sl['floor']}, "
                  f"x={sl['x']}, y={sl['y']}) -> renamed {new}; fix the label in lot.json if you know it")
            sl["id"] = new

    # a lift/stair only links floors if it exists on more than one floor
    links: dict[str, int] = {}
    for p in points:
        if p.get("link"):
            links[p["link"]] = links.get(p["link"], 0) + 1
    for p in points:
        if p.get("link") and links[p["link"]] < 2:
            p["link"] = None

    meters_per_unit = args.feet_per_inch / 72 * 0.3048  # 1 PDF point = 1/72 inch
    lot = {"format": "floorplan", "name": args.name, "meters_per_unit": round(meters_per_unit, 5),
           "cell": args.cell, "source": Path(args.pdf).name,
           "floors": floors, "slots": slots, "points": points, "cameras": []}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(lot, separators=(",", ":")))
    print(f"wrote {args.out}: {len(floors)} floors, {len(slots)} slots, {len(points)} points, "
          f"{Path(args.out).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
