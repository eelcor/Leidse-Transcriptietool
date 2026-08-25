"""Glossary plugin-structuur: /api/glossaries leest woordenlijst-bestanden uit een map."""
import pytest

from app.api.routes import _glossary_name_from_filename, get_glossaries
from app.config import get_settings


def test_name_from_filename():
    assert _glossary_name_from_filename("10-ruimtelijk-en-omgeving.txt") == "Ruimtelijk en omgeving"
    assert _glossary_name_from_filename("sociaal_domein.md") == "Sociaal domein"


@pytest.mark.asyncio
async def test_get_glossaries_reads_dir(tmp_path, monkeypatch):
    (tmp_path / "10-test.txt").write_text(
        "# naam: Testlijst\n# een sectie-commentaar\nOmgevingswet\n\nBOPA\n", encoding="utf-8")
    (tmp_path / "_README.md").write_text("dit is geen glossary\n", encoding="utf-8")
    (tmp_path / "leeg.txt").write_text("# alleen commentaar\n", encoding="utf-8")
    monkeypatch.setenv("GLOSSARY_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        res = await get_glossaries()
    finally:
        monkeypatch.delenv("GLOSSARY_DIR", raising=False)
        get_settings.cache_clear()

    assert len(res) == 1                       # _README overgeslagen, lege lijst weggelaten
    g = res[0]
    assert g["name"] == "Testlijst"            # uit '# naam:'-regel
    assert "Omgevingswet" in g["terms"] and "BOPA" in g["terms"]
    assert "commentaar" not in g["terms"]      # #-regels genegeerd


@pytest.mark.asyncio
async def test_get_glossaries_missing_dir(monkeypatch):
    monkeypatch.setenv("GLOSSARY_DIR", "/bestaat/echt/niet")
    get_settings.cache_clear()
    try:
        assert await get_glossaries() == []
    finally:
        monkeypatch.delenv("GLOSSARY_DIR", raising=False)
        get_settings.cache_clear()
