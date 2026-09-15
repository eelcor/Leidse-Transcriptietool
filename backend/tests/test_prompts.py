"""Tests voor het bouwen van LLM-messages, incl. basisbescherming tegen prompt injectie."""
from app.prompts import B1_KIND, build_messages, pop_simple_language


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


def test_b1_option_only_when_requested():
    plain = build_messages("x", ["volledig"], None, None)[0]["content"]
    simple = build_messages("x", ["volledig"], None, None, simple_language=True)[0]["content"]
    assert "TAALNIVEAU B1" not in plain
    assert "TAALNIVEAU B1" in simple


def test_pop_simple_language_roundtrip():
    # Sentinel eruit -> simple_language True, kinds behouden zonder sentinel.
    assert pop_simple_language(["volledig", B1_KIND]) == (["volledig"], True)
    # Zonder sentinel: ongewijzigd, False.
    assert pop_simple_language(["samenvatting"]) == (["samenvatting"], False)
    # Alleen de sentinel -> geen kinds meer over (None), True (bijv. bij een sjabloon-verslag).
    assert pop_simple_language([B1_KIND]) == (None, True)
    assert pop_simple_language(None) == (None, False)


def test_notes_note_preserves_attribution_and_drops_recording_opening():
    system = build_messages("Robin: Sam doet sociaal domein.", ["samenvatting"], None, None,
                            source_kind="notes")[0]["content"]
    assert "TOESCHRIJVING BEHOUDEN" in system
    assert "OPNAME-/CONSENTOPENING WEGLATEN" in system
    # Bij een gewoon transcript horen deze aantekeningen-regels er NIET te staan.
    audio = build_messages("x", ["samenvatting"], None, None, source_kind="audio")[0]["content"]
    assert "TOESCHRIJVING BEHOUDEN" not in audio
