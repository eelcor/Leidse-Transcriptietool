"""Fase 4 — LLM-koppeling & naamgeving.

- build_messages() voegt de sprekerlabel-instructie (data + versoepelde regel) alleen toe
  als diarized=True.
- create_report(): in placeholder-modus komen sprekernamen NIET in de DB; in direct-modus
  wel (in de context).
"""
from datetime import datetime, timezone

from app.prompts import build_messages


def test_build_messages_diarized_adds_speaker_note():
    msgs = build_messages("SPREKER_A: hoi\nSPREKER_B: daar", ["samenvatting"], None, None, diarized=True)
    system = msgs[0]["content"]
    assert "SPREKERLABELS" in system            # versoepelde regel + labels-als-data
    user = msgs[1]["content"]
    assert "SPREKER_A: hoi" in user              # labels staan binnen het (data-)transcriptblok
    assert "=== BEGIN TRANSCRIPT" in user


def test_build_messages_default_has_no_speaker_note():
    msgs = build_messages("gewoon transcript", ["samenvatting"], None, None)
    assert "SPREKERLABELS" not in msgs[0]["content"]


async def _seed_transcribed(sid: str):
    from app.db import get_sessionmaker
    from app.models import Session, SessionStatus

    maker = get_sessionmaker()
    now = datetime.now(timezone.utc)
    async with maker() as db:
        db.add(Session(
            id=sid, status=SessionStatus.TRANSCRIBED, language="nl",
            transcript="hoi daar", created_at=now, updated_at=now,
        ))
        await db.commit()


async def test_report_placeholder_drops_speaker_names(client):
    """SPEAKER_NAMES_MODE=placeholder (default): namen mogen niet in de opgeslagen payload."""
    from app.db import get_sessionmaker
    from app.models import Report
    from app.tokens import new_token

    sid = new_token()
    await _seed_transcribed(sid)
    r = await client.post(
        f"/api/sessions/{sid}/reports",
        json={"kinds": ["samenvatting"], "context": "Projectoverleg",
              "speaker_names": {"SPREKER_A": "Jan", "SPREKER_B": "Marie"}},
    )
    assert r.status_code == 200
    rid = r.json()["id"]
    maker = get_sessionmaker()
    async with maker() as db:
        rep = await db.get(Report, rid)
        assert "Jan" not in (rep.context or "")
        assert "Marie" not in (rep.context or "")
        assert "Projectoverleg" in (rep.context or "")   # eigen context blijft wel bewaard


async def test_report_direct_includes_speaker_names(client, monkeypatch):
    """SPEAKER_NAMES_MODE=direct: namen gaan mee in de context (en dus in de DB)."""
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.models import Report
    from app.tokens import new_token

    monkeypatch.setenv("SPEAKER_NAMES_MODE", "direct")
    get_settings.cache_clear()
    try:
        sid = new_token()
        await _seed_transcribed(sid)
        r = await client.post(
            f"/api/sessions/{sid}/reports",
            json={"kinds": ["samenvatting"], "context": "Projectoverleg",
                  "speaker_names": {"SPREKER_A": "Jan"}},
        )
        assert r.status_code == 200
        rid = r.json()["id"]
        maker = get_sessionmaker()
        async with maker() as db:
            rep = await db.get(Report, rid)
            assert "SPREKER_A = Jan" in rep.context
            assert "Projectoverleg" in rep.context
    finally:
        monkeypatch.delenv("SPEAKER_NAMES_MODE", raising=False)
        get_settings.cache_clear()
