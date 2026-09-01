"""Verslagprompt-hardening (geen mening/verbanden) + consent-tekst uit een bestand."""
import pytest

from app import prompts
from app.api.routes import _read_consent
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
