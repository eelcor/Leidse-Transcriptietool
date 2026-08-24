"""Abstracte STT-interface. Backends leveren tekst + (optioneel) timestamps.

Het woord-schema (`Word`) staat bewust LOS van de faster-whisper-datatypes: elke
backend normaliseert zijn eigen output naar `{start, end, text, probability}`, zodat
latere stappen (diarisatie/merge, zie ROADMAP.md) backend-onafhankelijk blijven.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Word:
    """Eén woord/token met tijdgrenzen. `text` is het token zoals de STT het teruggeeft
    (kan een leidende spatie bevatten); `probability` is optioneel (None als de backend
    het niet levert)."""

    start: float | None
    end: float | None
    text: str
    probability: float | None = None

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text, "probability": self.probability}


@dataclass
class Segment:
    start: float | None
    end: float | None
    text: str
    # Woordniveau-timestamps binnen dit segment (leeg als STT_WORD_TIMESTAMPS uit staat of
    # de backend geen woord-timing levert). Genormaliseerd naar het backend-agnostische Word.
    words: list[Word] = field(default_factory=list)


@dataclass
class TranscriptResult:
    text: str
    segments: list[Segment] = field(default_factory=list)

    def segments_as_dicts(self) -> list[dict]:
        """Segmenten als JSON-serialiseerbare dicts.

        De sleutel `words` wordt ALLEEN toegevoegd als er woord-timestamps zijn — zo blijft
        het pad zonder woord-timing byte-voor-byte gelijk aan voorheen (`{start,end,text}`)."""
        out: list[dict] = []
        for s in self.segments:
            d: dict = {"start": s.start, "end": s.end, "text": s.text}
            if s.words:
                d["words"] = [w.as_dict() for w in s.words]
            out.append(d)
        return out


class STTBackend(Protocol):
    """Contract voor alle STT-implementaties.

    load() is idempotent en (lazy) laadt het model in het geheugen; transcribe()
    is blokkerend/synchroon (GPU/CPU) en wordt door de worker in een executor
    gedraaid, begrensd door een semafoor (STT_CONCURRENCY).

    Bij word_timestamps=True vult een backend `Segment.words`; anders blijft die leeg.
    """

    name: str

    def load(self) -> None: ...

    def transcribe(self, wav_path: str, language: str, word_timestamps: bool,
                   hotwords: str | None = None) -> TranscriptResult: ...
