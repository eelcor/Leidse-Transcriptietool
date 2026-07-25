"""Abstracte STT-interface. Backends leveren tekst + (optioneel) timestamps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Segment:
    start: float | None
    end: float | None
    text: str


@dataclass
class TranscriptResult:
    text: str
    segments: list[Segment] = field(default_factory=list)

    def segments_as_dicts(self) -> list[dict]:
        return [{"start": s.start, "end": s.end, "text": s.text} for s in self.segments]


class STTBackend(Protocol):
    """Contract voor alle STT-implementaties.

    load() is idempotent en (lazy) laadt het model in het geheugen; transcribe()
    is blokkerend/synchroon (GPU/CPU) en wordt door de worker in een executor
    gedraaid, begrensd door een semafoor (STT_CONCURRENCY).
    """

    name: str

    def load(self) -> None: ...

    def transcribe(self, wav_path: str, language: str, word_timestamps: bool) -> TranscriptResult: ...
