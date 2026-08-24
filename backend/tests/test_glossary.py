"""Fase 4: woordenlijst/jargon stuurt de transcriptie (STT-hotwords) en het verslag
(terminologie in de context). Hier de config-/prompt-kant + de STT-signature-poort."""
import inspect

import pytest
from sqlalchemy import select

from app import prompts
from app.api.routes import _clean_report_config, _fold_glossary
from app.db import get_sessionmaker
from app.models import Report
from worker.stt.base import STTBackend


def test_glossary_block_and_fold():
    assert prompts.glossary_block("term1\nterm2").startswith("=== BEGIN TERMINOLOGIE")
    assert prompts.glossary_block("") == ""
    assert _fold_glossary(None, "ctx") == "ctx"
    folded = _fold_glossary("Leidse Ring Noord", "achtergrond")
    assert "BEGIN TERMINOLOGIE" in folded and "Leidse Ring Noord" in folded and "achtergrond" in folded


def test_base_instruction_mentions_terminology():
    assert "TERMINOLOGIE" in prompts.base_instruction()


def test_clean_config_glossary_folds_and_keeps_raw():
    cfg = _clean_report_config({"kinds": ["samenvatting"], "glossary": "Leidse Ring Noord\nomgevingsvisie"})
    assert "BEGIN TERMINOLOGIE" in cfg["context"]         # ingevouwen voor de LLM
    assert "Leidse Ring Noord" in cfg["context"]
    assert cfg["glossary"] == "Leidse Ring Noord\nomgevingsvisie"   # rauw voor STT-hotwords
    assert cfg["kinds"] == ["samenvatting"]


def test_clean_config_glossary_only_survives_without_report():
    cfg = _clean_report_config({"glossary": "term"})
    assert cfg is not None
    assert cfg["glossary"] == "term"
    assert cfg["kinds"] is None and cfg["custom_prompt"] is None


def test_stt_base_signature_accepts_hotwords():
    assert "hotwords" in inspect.signature(STTBackend.transcribe).parameters


@pytest.mark.asyncio
async def test_create_report_with_glossary_folds_terminology(client):
    files = {"file": ("t.txt", "We bespreken de omgevingsvisie.".encode(), "text/plain")}
    sid = (await client.post("/api/sessions/text", data={"source_kind": "transcript"}, files=files)).json()["id"]
    r = await client.post(f"/api/sessions/{sid}/reports",
                          json={"kinds": ["samenvatting"], "glossary": "omgevingsvisie"})
    assert r.status_code == 200, r.text
    maker = get_sessionmaker()
    async with maker() as db:
        rep = (await db.execute(select(Report).where(Report.id == r.json()["id"]))).scalar_one()
        assert "BEGIN TERMINOLOGIE" in (rep.context or "") and "omgevingsvisie" in rep.context
