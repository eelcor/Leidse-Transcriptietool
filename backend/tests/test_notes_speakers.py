"""Stap 2 (tweetraps-flow): eigen aantekeningen sturen het verslag; sprekersnamen per-verslag opt-in."""
import pytest
from sqlalchemy import select

from app.api.routes import _fold_notes
from app.db import get_sessionmaker
from app.models import Report


def test_fold_notes_wraps_as_data_block():
    ctx = _fold_notes("Belangrijk: besluit over budget vastleggen.", "bestaande context")
    assert "=== BEGIN EIGEN AANTEKENINGEN" in ctx and "=== EINDE EIGEN AANTEKENINGEN ===" in ctx
    assert "budget" in ctx and "bestaande context" in ctx


def test_fold_notes_noop_without_notes():
    assert _fold_notes(None, "ctx") == "ctx"
    assert _fold_notes("   ", None) is None


async def _text_session(client, body=b"Kim zegt dat project X doorgaat."):
    files = {"file": ("t.txt", body, "text/plain")}
    r = await client.post("/api/sessions/text", data={"source_kind": "transcript"}, files=files)
    return r.json()["id"]


@pytest.mark.asyncio
async def test_create_report_folds_notes_into_context(client):
    sid = await _text_session(client)
    r = await client.post(f"/api/sessions/{sid}/reports",
                          json={"kinds": ["samenvatting"], "notes": "Zeker terug: de deadline is 1 oktober."})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    maker = get_sessionmaker()
    async with maker() as db:
        rep = (await db.execute(select(Report).where(Report.id == rid))).scalar_one()
        assert "EIGEN AANTEKENINGEN" in rep.context and "1 oktober" in rep.context


@pytest.mark.asyncio
async def test_create_report_speaker_names_optin_folds_even_in_placeholder(client):
    # Default server-modus is 'placeholder'; tóch moeten meegestuurde namen (opt-in) invouwen.
    sid = await _text_session(client)
    r = await client.post(f"/api/sessions/{sid}/reports",
                          json={"kinds": ["samenvatting"], "speaker_names": {"SPREKER_A": "Kim"}})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    maker = get_sessionmaker()
    async with maker() as db:
        rep = (await db.execute(select(Report).where(Report.id == rid))).scalar_one()
        assert "SPREKER_A = Kim" in rep.context
