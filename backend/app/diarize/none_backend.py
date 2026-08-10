"""No-op diarisatie-backend (default). Levert geen spreker-turns; het gedrag van de
tool is identiek aan de opstelling zonder diarisatie."""
from __future__ import annotations

from .base import DiarizeBackend, SpeakerTurn


class NoneDiarizeBackend(DiarizeBackend):
    name = "none"

    def load(self) -> None:  # niets te laden
        return None

    def diarize(
        self, wav_path: str, min_speakers: int | None = None, max_speakers: int | None = None
    ) -> list[SpeakerTurn]:
        return []
