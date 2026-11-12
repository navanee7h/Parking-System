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
        assert s["total"] == 76 and "plate" not in s["slots"][0]

        r = c.get("/api/search", params={"q": "KA05MH1234"}).json()
        assert r["exact"] and r["results"][0]["slot_id"] == "A05"

        route = c.get("/api/route", params={"from": "K2", "slot": "A05"}).json()
        assert route["distance_m"] > 0 and route["steps"]

        assert c.post("/api/ingest/plate", json={"camera_id": "x", "slot_id": "A01",
                      "plate": "ap 01 zz 0001", "confidence": 0.9}).status_code == 401
        h = {"X-API-Key": "k"}
        c.post("/api/ingest/occupancy", json={"camera_id": "x", "slots": {"A01": True}}, headers=h)
        c.post("/api/ingest/plate", json={"camera_id": "x", "slot_id": "A01",
               "plate": "ap 01 zz 0001", "confidence": 0.9}, headers=h)
        assert c.get("/api/search", params={"q": "0001"}).json()["results"][0]["slot_id"] == "A01"

        c.post("/api/ingest/occupancy", json={"camera_id": "x", "slots": {"A01": False}}, headers=h)
        res = c.get("/api/search", params={"q": "AP01ZZ0001"}).json()["results"]
        assert all(m["slot_id"] != "A01" for m in res)

        nf = c.get("/api/nearest-free", params={"from": "GATE"}).json()
        assert nf["slot"]
