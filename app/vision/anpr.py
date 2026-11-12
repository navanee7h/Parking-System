"""Automatic number-plate recognition (ANPR) helpers.

`PlateReader` is pluggable. The default uses EasyOCR (optional dependency,
`pip install easyocr`). For production accuracy swap in a dedicated plate
detector (e.g. a YOLO plate model) + OCR - anything that returns `PlateRead`s.

Characters the OCR is unsure about become '?', so a partially hidden plate is
still stored (e.g. 'KA05M?12?4') and can be found with partial matching later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np


@dataclass
class PlateRead:
    text: str               # normalized, may contain '?'
    confidence: float       # 0..1
    bbox: tuple[int, int, int, int]  # x, y, w, h in frame pixels

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return x + w / 2, y + h / 2


class PlateReader(Protocol):
    def read(self, frame: np.ndarray) -> list[PlateRead]: ...


def clean_plate_text(raw: str) -> str:
    """Uppercase, drop spaces/dashes, turn junk characters into '?'."""
    raw = raw.upper().strip()
    raw = re.sub(r"[\s\-\.·]", "", raw)
    return re.sub(r"[^A-Z0-9]", "?", raw)


def looks_like_plate(text: str) -> bool:
    known = len(text.replace("?", ""))
    return 4 <= len(text) <= 12 and known >= 3 and any(c.isdigit() for c in text)


def merge_reads(reads: list[PlateRead]) -> PlateRead | None:
    """Combine several reads of the same car over time.

    Reads of the same length are merged position by position (confidence-weighted
    vote), so a '?' in one frame is filled in by another frame that saw it.
    """
    if not reads:
        return None
    by_len: dict[int, list[PlateRead]] = {}
    for r in reads:
        by_len.setdefault(len(r.text), []).append(r)
    group = max(by_len.values(), key=lambda g: sum(r.confidence for r in g))
    chars = []
    for i in range(len(group[0].text)):
        votes: dict[str, float] = {}
        for r in group:
            if r.text[i] != "?":
                votes[r.text[i]] = votes.get(r.text[i], 0) + r.confidence
        chars.append(max(votes, key=votes.get) if votes else "?")
    best = max(group, key=lambda r: r.confidence)
    conf = min(1.0, sum(r.confidence for r in group) / len(group) + 0.05 * (len(group) - 1))
    return PlateRead("".join(chars), round(conf, 3), best.bbox)


class EasyOCRPlateReader:
    def __init__(self, languages=("en",), min_conf: float = 0.2, char_conf: float = 0.45, gpu: bool = False):
        import easyocr  # optional dependency
        self._reader = easyocr.Reader(list(languages), gpu=gpu)
        self.min_conf = min_conf
        self.char_conf = char_conf

    def read(self, frame: np.ndarray) -> list[PlateRead]:
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        results = self._reader.readtext(
            grey, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789- ", paragraph=False)
        out = []
        for box, text, conf in results:
            if conf < self.min_conf:
                continue
            plate = clean_plate_text(text)
            if conf < self.char_conf:
                # whole read is shaky: keep only digits/letters from the confident tail
                plate = plate if len(plate) <= 4 else "?" * (len(plate) - 4) + plate[-4:]
            if not looks_like_plate(plate):
                continue
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            out.append(PlateRead(plate, float(conf), (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))))
        return out


def assign_to_slot(read: PlateRead, rois: dict[str, list[list[int]]]) -> str | None:
    """Which slot polygon contains the plate's centre (or is nearest to it)."""
    cx, cy = read.center
    best, best_d = None, -1e9
    for sid, poly in rois.items():
        d = cv2.pointPolygonTest(np.array(poly, np.int32), (cx, cy), True)
        if d > best_d:
            best, best_d = sid, d
    return best if best_d > -40 else None  # allow plate slightly outside the ROI
