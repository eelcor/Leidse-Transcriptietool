"""Fase 2 — diarize-backend achter een interface + orchestratie.

Draait zonder Redis/GPU: gemockte diarizer + SQLite (via conftest-env). Controleert dat
'none' een no-op is, dat een succesvolle run de rij vult, en dat een fout in de diarizer
de job NIET laat klappen (soft-fail).
"""
from datetime import datetime, timezone

import pytest

from app.db import get_sessionmaker, init_db
from app.diarize.base import SpeakerTurn
from app.diarize.none_backend import NoneDiarizeBackend
from app.diarize.run import run_diarization
from app.models import Diarization, DiarizationStatus, Session, SessionStatus
from app.tokens import new_token

# asyncio_mode=auto (pytest.ini) detecteert async tests vanzelf; geen module-brede mark,
# zodat de synchrone factory-test niet onterecht als asyncio wordt gemarkeerd.


class _FakeBackend:
    name = "fake"

    def __init__(self, turns=None, exc=None):
        self._turns = turns or []
        self._exc = exc

    def load(self):
        return None

    def diarize(self, wav_path, min_speakers=None, max_speakers=None):
        if self._exc is not None:
            raise self._exc
        return self._turns


async def _seed(maker) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    sid, did = new_token(), new_token()
    async with maker() as db:
        db.add(Session(
            id=sid, status=SessionStatus.TRANSCRIBED, language="nl",
            transcript="hoi daar", created_at=now, updated_at=now,
        ))
        db.add(Diarization(
            id=did, session_id=sid, status=DiarizationStatus.QUEUED,
            backend="fake", model="m", created_at=now, updated_at=now,
        ))
        await db.commit()
    return sid, did


async def test_none_backend_is_noop():
    assert NoneDiarizeBackend().diarize("audio.wav") == []


async def test_run_diarization_success_labels_and_counts():
    await init_db()
    maker = get_sessionmaker()
    sid, did = await _seed(maker)
    # Drie turns, twee unieke sprekers.
    backend = _FakeBackend(turns=[
        SpeakerTurn(0.0, 1.0, "SPEAKER_00"),
        SpeakerTurn(1.0, 2.0, "SPEAKER_01"),
        SpeakerTurn(2.0, 3.0, "SPEAKER_00"),
    ])
    res = await run_diarization(maker, sid, did, backend)
    assert res == "ok"
    async with maker() as db:
        d = await db.get(Diarization, did)
        assert d.status == DiarizationStatus.DONE
        assert d.num_speakers == 2
        assert d.payload["num_speakers"] == 2
        assert len(d.payload["turns"]) == 3
        assert d.payload["backend"] == "fake"
        assert d.error is None


async def test_run_diarization_soft_fails_without_raising():
    await init_db()
    maker = get_sessionmaker()
    sid, did = await _seed(maker)
    backend = _FakeBackend(exc=RuntimeError("pyannote kapot"))
    # Mag NIET raisen: de job blijft heel, alleen de rij wordt failed.
    res = await run_diarization(maker, sid, did, backend)
    assert res == "failed"
    async with maker() as db:
        d = await db.get(Diarization, did)
        assert d.status == DiarizationStatus.FAILED
        assert d.error and "RuntimeError" in d.error
        assert d.payload is None


async def test_run_diarization_gone_when_missing():
    await init_db()
    maker = get_sessionmaker()
    res = await run_diarization(maker, "no-such-session", "no-such-diar", _FakeBackend())
    assert res == "gone"


def test_to_annotation_handles_3x_and_4x():
    """3.x: het resultaat IS al een Annotation. 4.x: DiarizeOutput met speaker_diarization en
    exclusive_speaker_diarization. Pure helper — geen pyannote nodig."""
    from app.diarize.pyannote_backend import _to_annotation

    class _Ann:
        def itertracks(self, yield_label=False):
            return []

    ann = _Ann()
    assert _to_annotation(ann) is ann                    # 3.x passthrough

    class _DiarizeOutput:
        def __init__(self):
            self.speaker_diarization = _Ann()
            self.exclusive_speaker_diarization = _Ann()

    out = _DiarizeOutput()
    assert _to_annotation(out) is out.speaker_diarization             # 4.x standaard
    assert _to_annotation(out, exclusive=True) is out.exclusive_speaker_diarization


def test_factory_none_and_unknown(monkeypatch):
    import app.diarize.factory as factory
    from app.config import get_settings

    def _reset(value):
        monkeypatch.setenv("DIARIZE_BACKEND", value)
        get_settings.cache_clear()
        factory._instance = None

    try:
        _reset("none")
        assert factory.get_diarize_backend().name == "none"

        _reset("bogus")
        with pytest.raises(ValueError):
            factory.get_diarize_backend()
    finally:
        monkeypatch.delenv("DIARIZE_BACKEND", raising=False)
        get_settings.cache_clear()
        factory._instance = None
