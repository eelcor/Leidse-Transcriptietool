"""Fase 1 — woordniveau-timestamps: normalisatie naar het backend-agnostische Word-schema.

Draait zonder model/GPU: `_normalize_words` is puur en duck-typed, en `segments_as_dicts`
is een gewone datatransformatie.
"""
from dataclasses import dataclass

from worker.stt.base import Segment, TranscriptResult, Word
from worker.stt.faster_whisper_backend import _normalize_words


@dataclass
class _FakeWord:
    """Bootst een faster-whisper-woordobject na (velden .word/.start/.end/.probability)."""
    word: str
    start: float | None = None
    end: float | None = None
    probability: float | None = None


def test_normalize_words_maps_all_fields():
    raw = [_FakeWord(word=" Hallo", start=0.0, end=0.5, probability=0.98)]
    words = _normalize_words(raw)
    assert len(words) == 1
    w = words[0]
    assert w.text == " Hallo"          # token behoudt de spatie zoals de STT 'm levert
    assert w.start == 0.0 and w.end == 0.5
    assert w.probability == 0.98


def test_normalize_words_handles_missing_fields_and_empty():
    # Object zonder start/end/probability -> None; None-input -> lege lijst.
    class _Bare:
        word = "x"
    words = _normalize_words([_Bare()])
    assert words[0].text == "x"
    assert words[0].start is None and words[0].end is None and words[0].probability is None
    assert _normalize_words(None) == []
    assert _normalize_words([]) == []


def test_normalize_words_skips_wordless_tokens():
    class _NoWord:
        start = 1.0
        end = 2.0
        # geen .word-attribuut -> getattr(..., "word", None) is None -> overslaan
    assert _normalize_words([_NoWord()]) == []


def test_segments_as_dicts_omits_words_when_empty():
    """Zonder woord-timing blijft de output byte-voor-byte {start,end,text} (regressie)."""
    res = TranscriptResult(text="hoi", segments=[Segment(start=0.0, end=1.0, text="hoi")])
    assert res.segments_as_dicts() == [{"start": 0.0, "end": 1.0, "text": "hoi"}]


def test_segments_as_dicts_includes_words_when_present():
    seg = Segment(
        start=0.0, end=1.0, text="hoi daar",
        words=[Word(0.0, 0.4, "hoi", 0.9), Word(0.5, 1.0, " daar", 0.8)],
    )
    res = TranscriptResult(text="hoi daar", segments=[seg])
    out = res.segments_as_dicts()
    assert out[0]["text"] == "hoi daar"
    assert out[0]["words"] == [
        {"start": 0.0, "end": 0.4, "text": "hoi", "probability": 0.9},
        {"start": 0.5, "end": 1.0, "text": " daar", "probability": 0.8},
    ]
