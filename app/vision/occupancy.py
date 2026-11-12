"""Decide whether each parking slot in a camera frame is occupied.

Each slot is a polygon (ROI) in the camera image. Two signals are used:
  * difference from a reference photo of the *empty* lot (best, if you have one),
  * edge density inside the ROI (cars have lots of edges, bare floor does not).
A slot must look the same for `stable_frames` frames in a row before it flips,
so people walking past do not toggle it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class OccupancyDetector:
    rois: dict[str, list[list[int]]]
    reference: np.ndarray | None = None
    diff_threshold: float = 28.0     # mean abs grey-level difference vs empty frame
    edge_threshold: float = 0.06     # fraction of edge pixels inside the ROI
    stable_frames: int = 3
    _masks: dict[str, np.ndarray] = field(default_factory=dict, init=False)
    _state: dict[str, bool] = field(default_factory=dict, init=False)
    _streak: dict[str, int] = field(default_factory=dict, init=False)

    def _mask(self, slot_id: str, shape) -> np.ndarray:
        m = self._masks.get(slot_id)
        if m is None or m.shape != shape[:2]:
            m = np.zeros(shape[:2], np.uint8)
            cv2.fillPoly(m, [np.array(self.rois[slot_id], np.int32)], 255)
            self._masks[slot_id] = m
        return m

    def raw_scores(self, frame: np.ndarray) -> dict[str, bool]:
        grey = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        ref = None
        if self.reference is not None:
            ref = cv2.GaussianBlur(cv2.cvtColor(self.reference, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        edges = cv2.Canny(grey, 60, 160)
        out = {}
        for sid in self.rois:
            mask = self._mask(sid, grey.shape)
            area = max(1, int(np.count_nonzero(mask)))
            edge_ratio = np.count_nonzero(edges & mask) / area
            if ref is not None:
                diff = cv2.absdiff(grey, ref)
                mean_diff = float(cv2.mean(diff, mask=mask)[0])
                out[sid] = mean_diff > self.diff_threshold or edge_ratio > self.edge_threshold * 2
            else:
                out[sid] = edge_ratio > self.edge_threshold
        return out

    def update(self, frame: np.ndarray) -> dict[str, bool]:
        """Returns only slots whose *stable* state changed on this frame."""
        changed = {}
        for sid, occ in self.raw_scores(frame).items():
            if self._state.get(sid) == occ:
                self._streak[sid] = 0
                continue
            self._streak[sid] = self._streak.get(sid, 0) + 1
            if self._streak[sid] >= self.stable_frames or sid not in self._state:
                self._state[sid] = occ
                self._streak[sid] = 0
                changed[sid] = occ
        return changed
