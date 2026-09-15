"""Fase 2: tekst als bron (aantekeningen/transcript) -> verslag zonder STT,
en de aantekeningen-framing in de prompt."""
import pytest

from app import prompts
from app.models import Report, Session, SessionStatus
from app.db import get_sessionmaker
from sqlalchemy import select


def test_notes_source_kind_adds_note_and_relabels():
    msgs = prompts.build_messages("Kim opent. Besluit X.", ["volledig"], None, None, source_kind="notes")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "BRONSOORT — AANTEKENINGEN" in system      # _NOTES_NOTE aanwezig
    assert "BEGIN AANTEKENINGEN" in user               # herlabelde DATA-enveloppe
    assert "BEGIN TRANSCRIPT" not in user


def test_default_source_kind_is_transcript_framing():
    msgs = prompts.build_messages("x", ["volledig"], None, None)  # default = audio/transcript
    assert "BEGIN TRANSCRIPT" in msgs[1]["content"]
    assert "BRONSOORT — AANTEKENINGEN" not in msgs[0]["content"]


def test_transcript_source_kind_uses_transcript_framing():
    msgs = prompts.build_messages("x", ["volledig"], None, None, source_kind="transcript")
    assert "BEGIN TRANSCRIPT" in msgs[1]["content"]
    assert "BRONSOORT — AANTEKENINGEN" not in msgs[0]["content"]


@pytest.mark.asyncio
async def test_text_session_from_file_is_transcribed_without_auto_report(client):
    """Tweetraps-flow: tekst uploaden is stap 1 (het 'transcript'). Zonder expliciete verslag-opdracht
    wordt er GEEN verslag ingepland — dat doet de gebruiker in stap 2 op het resultaatscherm."""
    files = {"file": ("notulen.txt", "Notulen: Kim opent. Besluit X genomen.".encode(), "text/plain")}
    r = await client.post("/api/sessions/text", data={"source_kind": "notes"}, files=files)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    maker = get_sessionmaker()
    async with maker() as db:
        sess = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
        assert sess.status == SessionStatus.TRANSCRIBED
        assert sess.source == "notes"
        assert "Kim opent" in (sess.transcript or "")
        reports = (await db.execute(select(Report).where(Report.session_id == sid))).scalars().all()
        assert len(reports) == 0
    assert len(client.enqueued["report"]) == 0


@pytest.mark.asyncio
async def test_text_session_with_explicit_report_still_enqueues(client):
    """Vraagt de caller expliciet om een verslag (report-config), dan plant de tekst-sessie dat wél in."""
    import json
    files = {"file": ("notulen.txt", "Notulen: Kim opent. Besluit X genomen.".encode(), "text/plain")}
    r = await client.post("/api/sessions/text",
                          data={"source_kind": "notes", "report": json.dumps({"kinds": ["volledig"]})},
                          files=files)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    maker = get_sessionmaker()
    async with maker() as db:
        reports = (await db.execute(select(Report).where(Report.session_id == sid))).scalars().all()
        assert len(reports) == 1
    assert len(client.enqueued["report"]) == 1


@pytest.mark.asyncio
async def test_text_session_empty_is_rejected(client):
    files = {"file": ("leeg.txt", b"   ", "text/plain")}
    r = await client.post("/api/sessions/text", data={"source_kind": "notes"}, files=files)
    assert r.status_code == 422
