"""Spreker-diarisatie (GERESERVEERD — roadmap, nog niet geïmplementeerd).

Dit is de extensiehaak: ná STT kunnen de segments van sprekerlabels worden
voorzien (wie zegt wat), zodat verslagen betrouwbaar sprekers kunnen benoemen in
plaats van neutraal te blijven. De standaardimplementatie is een NO-OP, zodat de
bestaande pijplijn ongewijzigd werkt tot er een backend wordt toegevoegd.

Resourceoverweging (waarom opt-in): pyannote draait bij voorkeur op GPU en kost
extra VRAM + verwerkingstijd bovenop STT. Op deze dev-box concurreert dat met de
V100's (Qwen) en de STT. Daarom expliciet achter DIARIZATION_ENABLED. Zie
ROADMAP.md voor het gefaseerde plan en de integratiepunten.
"""
from __future__ import annotations

import logging

from app.config import get_settings

log = logging.getLogger("transcribe.diarize")


def apply_diarization(wav_path: str, segments: list[dict] | None) -> list[dict] | None:
    """Voeg 'speaker'-labels toe aan de STT-segments. No-op tenzij een backend actief is.

    Contract voor een toekomstige backend:
      - input: pad naar de 16kHz mono wav + de STT-segments (met start/eind/tekst);
      - output: dezelfde segments, elk aangevuld met een 'speaker'-sleutel
        (bv. "SPREKER_1"); aantal en volgorde van segments blijven gelijk.
    """
    s = get_settings()
    if not s.diarization_enabled or s.diarization_backend == "none":
        return segments  # standaardpad: geen diarisatie
    # TODO(roadmap): backend laden (bv. pyannote via s.diarization_model + s.hf_token),
    # de speaker-turns overlappen met de STT-segments en per segment een label zetten.
    log.warning(
        "Diarisatie aangevraagd (backend=%s) maar nog niet geïmplementeerd; overgeslagen.",
        s.diarization_backend,
    )
    return segments
