"""Tests voor het bouwen van LLM-messages, incl. basisbescherming tegen prompt injectie."""
from app.prompts import build_messages


def test_messages_harden_and_delimit():
    msgs = build_messages("Dit is het transcript.", ["volledig"], None, "Overleg 24 juli")
    system = msgs[0]["content"]
    user = msgs[1]["content"]
    # System-instructie bevat de hardening.
    assert "BEVEILIGING" in system
    assert "DATA" in system
    # Gebruikersinhoud staat afgebakend als materiaal, niet als opdracht.
    assert "=== BEGIN TRANSCRIPT" in user and "=== EINDE TRANSCRIPT ===" in user
    assert "=== BEGIN CONTEXT" in user
    assert "Dit is het transcript." in user


def test_messages_without_context_have_no_context_block():
    msgs = build_messages("Alleen transcript.", ["samenvatting"], None, None)
    user = msgs[1]["content"]
    assert "BEGIN CONTEXT" not in user
    assert "=== BEGIN TRANSCRIPT" in user


def test_custom_prompt_is_the_task_and_still_hardened():
    msgs = build_messages("x", None, "Vat samen in 3 bullets.", None)
    assert "Vat samen in 3 bullets." in msgs[0]["content"]
    assert "BEVEILIGING" in msgs[0]["content"]
