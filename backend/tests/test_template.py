"""Fase 3: sjabloon met vragen -> beantwoord-de-vragen-modus (vervangt het verslag)."""
import pytest
from sqlalchemy import select

from app import prompts
from app.api.routes import _clean_report_config, _fold_template
from app.db import get_sessionmaker
from app.models import Report


def test_template_task_loads_from_prompts_md():
    t = prompts.template_task()
    assert "Beantwoord ELKE vraag" in t
    assert "Niet in het materiaal besproken" in t


def test_fold_template_sets_instruction_and_data_block():
    custom, context = _fold_template("1. Wat is besloten?", None, None)
    assert custom == prompts.template_task()
    assert "BEGIN VRAGEN" in context and "1. Wat is besloten?" in context


def test_fold_template_noop_without_template():
    assert _fold_template(None, "eigen prompt", "ctx") == ("eigen prompt", "ctx")


def test_clean_report_config_folds_template_and_drops_kinds():
    cfg = _clean_report_config({"kinds": ["samenvatting"], "template": "1. Vraag?", "context": "achtergrond"})
    assert cfg["kinds"] is None                       # sjabloon vervangt het verslag
    assert cfg["custom_prompt"] == prompts.template_task()
    assert "BEGIN VRAGEN" in cfg["context"] and "achtergrond" in cfg["context"]


@pytest.mark.asyncio
async def test_create_report_with_template(client):
    # sessie met transcript via het tekst-endpoint
    files = {"file": ("t.txt", b"Jan zegt dat project X doorgaat. Over budget is niets gezegd.", "text/plain")}
    sid = (await client.post("/api/sessions/text", data={"source_kind": "transcript"}, files=files)).json()["id"]

    r = await client.post(f"/api/sessions/{sid}/reports",
                          json={"template": "1. Gaat project X door?\n2. Wat is het budget?"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    maker = get_sessionmaker()
    async with maker() as db:
        rep = (await db.execute(select(Report).where(Report.id == rid))).scalar_one()
        assert rep.kinds is None
        assert rep.custom_prompt == prompts.template_task()
        assert "BEGIN VRAGEN" in rep.context and "budget" in rep.context
