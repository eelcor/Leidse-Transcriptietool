"""Verslagprompt-hardening (geen mening/verbanden) + consent-/notice-tekst uit een bestand."""
import pytest

from app import prompts
from app.api.routes import _hash8, _read_consent, _read_notice
from app.config import get_settings


def test_base_instruction_forbids_opinion_and_relations():
    b = prompts.base_instruction()
    assert "GEEN eigen mening" in b            # geen oordeel/interpretatie
    assert "LEG GEEN VERBANDEN" in b           # geen niet-benoemde verbanden/conclusies


def test_read_consent_from_file(tmp_path, monkeypatch):
    f = tmp_path / "consent.md"
    f.write_text("Dit overleg wordt opgenomen. Bezwaar? Nu kenbaar maken.\n", encoding="utf-8")
    monkeypatch.setenv("CONSENT_FILE", str(f))
    get_settings.cache_clear()
    try:
        assert "Dit overleg wordt opgenomen" in _read_consent()
    finally:
        monkeypatch.delenv("CONSENT_FILE", raising=False)
        get_settings.cache_clear()


def test_read_consent_missing_returns_empty(monkeypatch):
    monkeypatch.setenv("CONSENT_FILE", "/bestaat/niet/consent.md")
    get_settings.cache_clear()
    try:
        assert _read_consent() == ""
    finally:
        monkeypatch.delenv("CONSENT_FILE", raising=False)
        get_settings.cache_clear()


def test_read_notice_from_file(tmp_path, monkeypatch):
    f = tmp_path / "notice.md"
    f.write_text("De tool is vernieuwd.\n", encoding="utf-8")
    monkeypatch.setenv("NOTICE_FILE", str(f))
    get_settings.cache_clear()
    try:
        assert _read_notice() == "De tool is vernieuwd."
    finally:
        monkeypatch.delenv("NOTICE_FILE", raising=False)
        get_settings.cache_clear()


def test_read_notice_missing_returns_empty(monkeypatch):
    monkeypatch.setenv("NOTICE_FILE", "/bestaat/niet/notice.md")
    get_settings.cache_clear()
    try:
        assert _read_notice() == ""
    finally:
        monkeypatch.delenv("NOTICE_FILE", raising=False)
        get_settings.cache_clear()


def test_notice_version_is_stable_and_content_derived():
    # De banner-versie is een korte hash van de inhoud: gelijk bij gelijke tekst, anders bij andere tekst.
    assert _hash8("a") == _hash8("a")
    assert _hash8("a") != _hash8("b")
    assert len(_hash8("wat dan ook")) == 8


@pytest.mark.asyncio
async def test_config_exposes_notice(client, tmp_path, monkeypatch):
    f = tmp_path / "notice.md"
    f.write_text("Nieuwe werkwijze.\n", encoding="utf-8")
    monkeypatch.setenv("NOTICE_FILE", str(f))
    get_settings.cache_clear()
    try:
        d = (await client.get("/api/config")).json()
        assert d["notice_text"] == "Nieuwe werkwijze."
        assert d["notice_version"] == _hash8("Nieuwe werkwijze.")
    finally:
        monkeypatch.delenv("NOTICE_FILE", raising=False)
        get_settings.cache_clear()
