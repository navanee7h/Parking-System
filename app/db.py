"""SQLite store for live slot status (occupancy + plate seen in each slot)."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from .plate_matcher import similarity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS slots (
                    slot_id    TEXT PRIMARY KEY,
                    occupied   INTEGER NOT NULL DEFAULT 0,
                    plate      TEXT,
                    plate_conf REAL,
                    camera_id  TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT, slot_id TEXT, kind TEXT, plate TEXT, camera_id TEXT
                );
            """)
            self._conn.commit()

    def ensure_slots(self, slot_ids) -> None:
        with self._lock:
            self._conn.executemany("INSERT OR IGNORE INTO slots(slot_id) VALUES (?)",
                                   [(s,) for s in slot_ids])
            self._conn.commit()

    def set_occupancy(self, slot_id: str, occupied: bool, camera_id: str | None = None) -> None:
        with self._lock:
            row = self._conn.execute("SELECT occupied FROM slots WHERE slot_id=?", (slot_id,)).fetchone()
            if row is None or bool(row["occupied"]) == occupied:
                return
            if occupied:
                self._conn.execute("UPDATE slots SET occupied=1, updated_at=?, camera_id=? WHERE slot_id=?",
                                   (_now(), camera_id, slot_id))
            else:  # car left -> forget its plate
                self._conn.execute("UPDATE slots SET occupied=0, plate=NULL, plate_conf=NULL, "
                                   "updated_at=?, camera_id=? WHERE slot_id=?", (_now(), camera_id, slot_id))
            self._conn.execute("INSERT INTO events(at, slot_id, kind, camera_id) VALUES (?,?,?,?)",
                               (_now(), slot_id, "arrive" if occupied else "leave", camera_id))
            self._conn.commit()

    def set_plate(self, slot_id: str, plate: str, conf: float, camera_id: str | None = None) -> None:
        """Store a plate read. For the same car keep the better read; a different car replaces it."""
        with self._lock:
            row = self._conn.execute("SELECT plate, plate_conf FROM slots WHERE slot_id=?", (slot_id,)).fetchone()
            if row is None:
                return
            old_plate, old_conf = row["plate"], row["plate_conf"] or 0.0
            different_car = old_plate is not None and similarity(plate, old_plate) < 0.6
            better = (old_plate is None or different_car or conf >= old_conf
                      or old_plate.count("?") > plate.count("?"))
            if better:
                self._conn.execute("UPDATE slots SET occupied=1, plate=?, plate_conf=?, camera_id=?, "
                                   "updated_at=? WHERE slot_id=?", (plate, conf, camera_id, _now(), slot_id))
                self._conn.execute("INSERT INTO events(at, slot_id, kind, plate, camera_id) VALUES (?,?,?,?,?)",
                                   (_now(), slot_id, "plate", plate, camera_id))
                self._conn.commit()

    def slots(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM slots ORDER BY slot_id")]

    def vehicles(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT slot_id, plate, plate_conf, updated_at FROM slots WHERE plate IS NOT NULL")]

    def is_empty(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM slots WHERE occupied=1").fetchone()[0] == 0
