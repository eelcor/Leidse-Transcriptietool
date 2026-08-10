"""Abstracte diarisatie-interface. Backends leveren spreker-turns over de audio."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SpeakerTurn:
    """Eén aaneengesloten spreekbeurt: [start, end) door één (rauw gelabelde) spreker.

    `speaker` is het rauwe label van de backend (bv. pyannote's "SPEAKER_00"); de merge
    (fase 3) hernummert naar stabiele labels SPREKER_A/B/… op volgorde van eerste spreekmoment.
    """

    start: float
    end: float
    speaker: str

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "speaker": self.speaker}


class DiarizeBackend(Protocol):
    """Contract voor alle diarisatie-implementaties.

    load() is idempotent en (lazy) laadt het model; diarize() is blokkerend/synchroon
    (GPU/CPU) en wordt door de worker in een executor gedraaid, begrensd door een semafoor
    (DIARIZE_CONCURRENCY). min/max_speakers zijn optionele hints (van het startscherm).
    """

    name: str

    def load(self) -> None: ...

    def diarize(
        self, wav_path: str, min_speakers: int | None = None, max_speakers: int | None = None
    ) -> list[SpeakerTurn]: ...
