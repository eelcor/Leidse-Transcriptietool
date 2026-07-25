"""Tests voor de statistiek-endpoints (anoniem)."""
import pytest

pytestmark = pytest.mark.asyncio

STATS_KEYS = {"totals", "by_hour", "by_weekday", "source", "formats", "satisfaction", "live", "processing"}


async def test_stats_endpoint(client):
    r = await client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert STATS_KEYS.issubset(body.keys())
    assert len(body["by_hour"]) == 24
    assert len(body["by_weekday"]) == 7


async def test_wait_endpoint(client):
    r = await client.get("/api/wait")
    assert r.status_code == 200
    assert "eta_seconds" in r.json()


async def test_created_event_from_upload(client):
    files = {"file": ("gesprek.mp3", b"fake-mp3-bytes", "audio/mpeg")}
    r = await client.post("/api/upload", files=files)
    assert r.status_code == 200
    stats = (await client.get("/api/stats")).json()
    assert stats["source"].get("upload", 0) >= 1
    assert stats["formats"].get("mp3", 0) >= 1
    # report_mode: geen verslag gevraagd -> "geen" of afwezig
    assert stats["report_modes"].get("geen", 0) >= 1


async def test_feedback_records_satisfaction(client):
    sid = (await client.post("/api/sessions", json={})).json()["id"]
    before = (await client.get("/api/stats")).json()["satisfaction"]["count"]
    r = await client.post(f"/api/sessions/{sid}/feedback", json={"stars": 5, "target": "verslag"})
    assert r.status_code == 200
    after = (await client.get("/api/stats")).json()["satisfaction"]
    assert after["count"] == before + 1
    assert after["avg"] is not None


async def test_feedback_rejects_bad_score(client):
    sid = (await client.post("/api/sessions", json={})).json()["id"]
    r = await client.post(f"/api/sessions/{sid}/feedback", json={"stars": 9})
    assert r.status_code == 422
