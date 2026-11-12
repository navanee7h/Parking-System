import os
import tempfile

os.environ["PARKING_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["PARKING_API_KEY"] = "k"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_end_to_end():
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        s = c.get("/api/slots").json()
        assert s["total"] == 890 and "plate" not in s["slots"][0]
        assert sum(f["total"] for f in s["floors"].values()) == 890

        r = c.get("/api/search", params={"q": "KA05MH1234"}).json()
        assert r["exact"]
        slot = r["results"][0]["slot_id"]
        assert r["results"][0]["floor_name"].startswith("Level")

        route = c.get("/api/route", params={"from": "V802", "slot": slot}).json()
        assert route["distance_m"] > 0 and route["steps"] and len(route["legs"]) == 2

        floor = c.get("/api/floors/1").json()
        assert floor["shapes"] and floor["texts"]

        assert c.post("/api/ingest/plate", json={"camera_id": "x", "slot_id": "1-101",
                      "plate": "ap 01 zz 0001", "confidence": 0.9}).status_code == 401
        h = {"X-API-Key": "k"}
        c.post("/api/ingest/occupancy", json={"camera_id": "x", "slots": {"1-101": True}}, headers=h)
        c.post("/api/ingest/plate", json={"camera_id": "x", "slot_id": "1-101",
               "plate": "ap 01 zz 0001", "confidence": 0.9}, headers=h)
        assert c.get("/api/search", params={"q": "0001"}).json()["results"][0]["slot_id"] == "1-101"

        c.post("/api/ingest/occupancy", json={"camera_id": "x", "slots": {"1-101": False}}, headers=h)
        res = c.get("/api/search", params={"q": "AP01ZZ0001"}).json()["results"]
        assert all(m["slot_id"] != "1-101" for m in res)

        nf = c.get("/api/nearest-free", params={"from": "ENTRY-1"}).json()
        assert nf["slot"]
