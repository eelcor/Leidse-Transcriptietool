"""STT via een extern OpenAI-compatibel `/v1/audio/transcriptions`-endpoint.

Zo offload je spraak-naar-tekst naar een aparte server (bijv. whisper.cpp-server
of een faster-whisper OpenAI-wrapper), net zoals de verslag-LLM al extern draait.
De worker heeft dan zelf geen STT-model, torch of GPU nodig — alleen ffmpeg voor
de resample naar 16kHz mono wav.

Robuust tegen verschillen tussen servers: probeert `verbose_json` (met segment-
timestamps) en valt terug op `json` (alleen tekst) als de server dat niet kent.
"""
from __future__ import annotations

import logging

from .base import Segment, STTBackend, TranscriptResult

log = logging.getLogger("transcribe.stt.openai")


class OpenAISTTBackend(STTBackend):
    name = "openai"

    def __init__(self, base_url: str, model: str, api_key: str = "not-needed", timeout: int = 600):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def load(self) -> None:
        # Niets te laden; het model draait op het externe endpoint.
        return

    def _post(self, wav_path: str, data: dict):
        import httpx

        headers = {}
        if self._api_key and self._api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self._api_key}"
        with open(wav_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            return httpx.post(
                f"{self._base_url}/audio/transcriptions",
                data=data, files=files, headers=headers, timeout=self._timeout,
            )

    def transcribe(self, wav_path: str, language: str, word_timestamps: bool) -> TranscriptResult:
        base = {"model": self._model}
        if language:
            base["language"] = language

        attempts = []
        if word_timestamps:
            attempts.append({**base, "response_format": "verbose_json",
                             "timestamp_granularities[]": "segment"})
        attempts.append({**base, "response_format": "json"})

        last = None
        for data in attempts:
            resp = self._post(wav_path, data)
            if resp.status_code < 400:
                return _parse(resp.json())
            last = resp
            log.info("STT-endpoint gaf %s bij response_format=%s; probeer eenvoudiger formaat.",
                     resp.status_code, data.get("response_format"))
        last.raise_for_status()  # geen enkele poging lukte -> gooi de laatste fout
        return TranscriptResult(text="", segments=[])  # pragma: no cover


def _parse(body: dict) -> TranscriptResult:
    text = (body.get("text") or "").strip()
    segments = []
    for s in body.get("segments") or []:
        segments.append(Segment(
            start=s.get("start"), end=s.get("end"),
            text=(s.get("text") or "").strip(),
        ))
    return TranscriptResult(text=text, segments=segments)
