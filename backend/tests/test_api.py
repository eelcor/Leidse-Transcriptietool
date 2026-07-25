"""Basale API-tests (SQLite + nep-queue, geen Redis/GPU nodig)."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_config_and_prompts(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["retention_workdays"] == 2
    assert body["max_upload_mb"] > 0

    r = await client.get("/api/prompts")
    keys = {s["key"] for s in r.json()["sections"]}
    assert {"samenvatting", "verslag", "actiepunten", "volledig"}.issubset(keys)


async def test_chunked_upload_flow(client):
    # 1) sessie aanmaken
    r = await client.post("/api/sessions", json={"language": "nl"})
    assert r.status_code == 200
    sid = r.json()["id"]
    assert len(sid) > 20  # hoge-entropie token

    # 2) chunk uploaden
    r = await client.put(
        f"/api/sessions/{sid}/audio",
        content=b"\x00\x01\x02\x03fake-audio",
        headers={"content-type": "audio/webm", "x-filename": "opname.webm"},
    )
    assert r.status_code == 200
    assert r.json()["received_bytes"] == 14

    # 3) afronden -> queued + job enqueued
    r = await client.post(f"/api/sessions/{sid}/complete")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert sid in client.enqueued["stt"]

    # 4) status
    r = await client.get(f"/api/sessions/{sid}/status")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert r.json()["has_transcript"] is False


async def test_single_shot_upload(client):
    files = {"file": ("test.wav", b"RIFFfakewavdata", "audio/wav")}
    r = await client.post("/api/upload", files=files)
    assert r.status_code == 200
    sid = r.json()["id"]
    assert r.json()["status"] == "queued"
    assert sid in client.enqueued["stt"]


async def test_unknown_session_is_404(client):
    r = await client.get("/api/sessions/does-not-exist/status")
    assert r.status_code == 404


async def test_report_requires_transcript(client):
    r = await client.post("/api/sessions", json={})
    sid = r.json()["id"]
    # Nog geen transcript -> 409
    r = await client.post(f"/api/sessions/{sid}/reports", json={"kinds": ["samenvatting"]})
    assert r.status_code == 409


async def test_empty_complete_is_400(client):
    r = await client.post("/api/sessions", json={})
    sid = r.json()["id"]
    # Geen audio geüpload -> complete faalt netjes.
    r = await client.post(f"/api/sessions/{sid}/complete")
    assert r.status_code == 400
