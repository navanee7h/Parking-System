import cv2
import numpy as np

from app.vision.anpr import PlateRead, assign_to_slot, clean_plate_text, merge_reads
from app.vision.occupancy import OccupancyDetector

ROIS = {"S1": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "S2": [[110, 0], [210, 0], [210, 100], [110, 100]]}


def test_merge_reads_fills_unknown_characters():
    reads = [PlateRead("KA05M?1234", 0.8, (0, 0, 1, 1)),
             PlateRead("K?05MH12?4", 0.7, (0, 0, 1, 1)),
             PlateRead("KA05MH1234", 0.6, (0, 0, 1, 1))]
    assert merge_reads(reads).text == "KA05MH1234"


def test_clean_plate_text():
    assert clean_plate_text("ka-05 mh#1234") == "KA05MH?1234"


def test_assign_to_slot():
    assert assign_to_slot(PlateRead("X", 1, (150, 40, 20, 10)), ROIS) == "S2"


def test_occupancy_detects_car_against_reference():
    empty = np.full((100, 220, 3), 90, np.uint8)
    frame = empty.copy()
    cv2.rectangle(frame, (10, 10), (90, 90), (20, 20, 200), -1)  # a "car" in S1
    for y in range(15, 85, 8):
        cv2.line(frame, (12, y), (88, y), (240, 240, 240), 2)
    det = OccupancyDetector(ROIS, reference=empty, stable_frames=2)
    first = det.update(frame)
    assert first == {"S1": True, "S2": False}
