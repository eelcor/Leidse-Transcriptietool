"""faster-whisper backend (default voor snelle/CPU-vriendelijke start).

LET OP (uit BOUWPROMPT): Whisper is bewust NIET de kwaliteits-default vanwege
gedocumenteerde regressies in large-v3. Gebruik daarom large-v2 als STT_MODEL.
Op de krappe dev-GPU (P1000, 4GB) of CPU: STT_DEVICE=cpu, STT_COMPUTE_TYPE=int8.
"""
from __future__ import annotations

import logging

from .base import Segment, STTBackend, TranscriptResult, Word

log = logging.getLogger("transcribe.stt.faster_whisper")


def _normalize_words(raw_words) -> list[Word]:
    """Zet faster-whisper's woordobjecten om naar het backend-agnostische Word-schema.

    Pure functie (duck-typed, geen faster-whisper-import) zodat ze zonder model/GPU te
    testen is. faster-whisper levert per woord `.word`, `.start`, `.end`, `.probability`;
    ontbrekende velden worden None. Woorden zonder tekst worden overgeslagen.
    """
    words: list[Word] = []
    for w in raw_words or []:
        text = getattr(w, "word", None)
        if text is None:
            continue
        words.append(
            Word(
                start=getattr(w, "start", None),
                end=getattr(w, "end", None),
                text=text,
                probability=getattr(w, "probability", None),
            )
        )
    return words


class FasterWhisperBackend(STTBackend):
    name = "faster_whisper"

    def __init__(self, model: str, device: str, compute_type: str):
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        log.info("faster-whisper laden: model=%s device=%s compute=%s",
                 self._model_name, self._device, self._compute_type)
        try:
            self._model = WhisperModel(
                self._model_name, device=self._device, compute_type=self._compute_type
            )
        except Exception as exc:  # pragma: no cover - hardware-afhankelijk
            log.warning("Laden op device=%s mislukt (%s); val terug op CPU/int8.",
                        self._device, exc)
            self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")

    def transcribe(self, wav_path: str, language: str, word_timestamps: bool) -> TranscriptResult:
        self.load()
        segments_iter, _info = self._model.transcribe(
            wav_path,
            language=language or None,
            word_timestamps=word_timestamps,
            vad_filter=False,  # VAD gebeurt optioneel client-side; server houdt audio intact
        )
        segments: list[Segment] = []
        texts: list[str] = []
        for seg in segments_iter:
            text = seg.text.strip()
            segments.append(Segment(
                start=seg.start, end=seg.end, text=text,
                words=_normalize_words(getattr(seg, "words", None)),
            ))
            texts.append(text)
        return TranscriptResult(text=" ".join(texts).strip(), segments=segments)
