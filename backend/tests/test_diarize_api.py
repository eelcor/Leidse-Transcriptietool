"""Fase 5 (backend-affordances) — resultaat met diarisatie + 'opnieuw indelen'-endpoint."""
from datetime import datetime, timezone

from app.db import get_sessionmaker
from app.models import Diarization, DiarizationStatus, Session, SessionStatus
from app.tokens import new_token


async def _seed_transcribed(sid: str):
    maker = get_sessionmaker()
    now = datetime.now(timezone.utc)
    async with maker() as db:
        db.add(Session(
            id=sid, status=SessionStatus.TRANSCRIBED, language="nl",
            transcript="hoi daar", created_at=now, updated_at=now,
        ))
        await db.commit()


async def test_result_includes_diarization(client):
    sid = new_token()
    await _seed_transcribed(sid)
    maker = get_sessionmaker()
    now = datetime.now(timezone.utc)
    async with maker() as db:
        db.add(Diarization(
            id=new_token(), session_id=sid, status=DiarizationStatus.DONE,
            backend="pyannote", model="m", num_speakers=2,
            payload={"segments": [
                {"start": 0.0, "end": 1.0, "speaker": "SPREKER_A", "text": "hoi"},
                {"start": 1.0, "end": 2.0, "speaker": "SPREKER_B", "text": "daar"},
            ]},
            created_at=now, updated_at=now,
        ))
        await db.commit()

    r = await client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    d = r.json()["diarization"]
    assert d is not None
    assert d["status"] == "done"
    assert d["num_speakers"] == 2
    assert d["speakers"] == ["SPREKER_A", "SPREKER_B"]
    assert len(d["segments"]) == 2
    assert d["segments"][0]["text"] == "hoi"


async def test_result_diarization_absent_by_default(client):
    sid = new_token()
    await _seed_transcribed(sid)
    r = await client.get(f"/api/sessions/{sid}")
    assert r.json()["diarization"] is None


async def test_rediarize_disabled_returns_409(client):
    """Default DIARIZE_BACKEND=none -> 'opnieuw indelen' is niet beschikbaar."""
    sid = new_token()
    await _seed_transcribed(sid)
    r = await client.post(f"/api/sessions/{sid}/rediarize", json={"participants": 3})
    assert r.status_code == 409


async def test_rediarize_enabled_creates_row_and_enqueues(client, monkeypatch):
    from app.config import get_settings
    from sqlalchemy import select

    monkeypatch.setenv("DIARIZE_BACKEND", "pyannote")
    get_settings.cache_clear()
    try:
        sid = new_token()
        await _seed_transcribed(sid)
        r = await client.post(f"/api/sessions/{sid}/rediarize", json={"participants": 3})
        assert r.status_code == 200
        assert r.json()["status"] == "queued"

        maker = get_sessionmaker()
        async with maker() as db:
            rows = (await db.execute(
                select(Diarization).where(Diarization.session_id == sid)
            )).scalars().all()
            assert len(rows) == 1
            assert rows[0].min_speakers == 3 and rows[0].max_speakers == 3
        # diarize-job ingepland (nep-queue uit conftest).
        assert any(s == sid for (s, _diar) in client.enqueued["diarize"])
    finally:
        monkeypatch.delenv("DIARIZE_BACKEND", raising=False)
        get_settings.cache_clear()
