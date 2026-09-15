"""B1 (eenvoudig taalniveau) als opt-in: migratie-vrij opgeslagen als sentinel in kinds."""
import pytest
from sqlalchemy import select

from app import prompts
from app.api.routes import _clean_report_config
from app.db import get_sessionmaker
from app.models import Report


def test_clean_report_config_adds_b1_sentinel_when_requested():
    cfg = _clean_report_config({"kinds": ["samenvatting"], "simple_language": True})
    assert cfg["kinds"] == ["samenvatting", prompts.B1_KIND]
    # Zonder de vlag geen sentinel.
    cfg2 = _clean_report_config({"kinds": ["samenvatting"]})
    assert prompts.B1_KIND not in cfg2["kinds"]


def test_clean_report_config_no_b1_without_a_report():
    # B1 mag in z'n eentje geen verslag afdwingen (geen kinds/custom -> None).
    assert _clean_report_config({"simple_language": True}) is None


@pytest.mark.asyncio
async def test_create_report_stores_b1_sentinel(client):
    files = {"file": ("t.txt", b"Kim zegt dat project X doorgaat.", "text/plain")}
    sid = (await client.post("/api/sessions/text", data={"source_kind": "transcript"}, files=files)).json()["id"]

    r = await client.post(f"/api/sessions/{sid}/reports",
                          json={"kinds": ["samenvatting"], "simple_language": True})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    maker = get_sessionmaker()
    async with maker() as db:
        rep = (await db.execute(select(Report).where(Report.id == rid))).scalar_one()
        assert prompts.B1_KIND in rep.kinds
        # De worker haalt de sentinel er weer uit -> echte kinds + simple_language True.
        clean, simple = prompts.pop_simple_language(rep.kinds)
        assert clean == ["samenvatting"] and simple is True
