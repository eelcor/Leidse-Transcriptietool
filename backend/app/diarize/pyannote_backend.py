"""pyannote.audio-diarisatiebackend (opt-in, DIARIZE_BACKEND=pyannote).

Werkt met zowel pyannote 3.x (speaker-diarization-3.1, default) als 4.x (community-1):
- de golfvorm wordt ZELF ingevoerd (16-bit PCM wav via de stdlib), zodat pyannote het bestand
  niet met torchcodec hoeft te decoderen — dat omzeilt de torchcodec/FFmpeg-laadfout in 4.x;
- het resultaat is in 3.x een Annotation en in 4.x een DiarizeOutput (met .speaker_diarization
  en .exclusive_speaker_diarization) — _to_annotation() haalt in beide gevallen de labels eruit.

Zwaar (torch + gated modellen): alle imports zijn lazy in load(). Draait in de aparte
diarize-worker. Kaart-pinning: binnen de container is de toegewezen GPU altijd cuda:0.

LET OP model/torch-combinatie (zie DEPLOY.md):
- 3.1  -> torch 2.6 (cu124), huggingface_hub<1.0.
- community-1 (4.x) -> torch 2.8 (cu126; behoudt sm_70/V100). Build met requirements-diarize4.txt.
"""
from __future__ import annotations

import logging

from .base import DiarizeBackend, SpeakerTurn

log = logging.getLogger("transcribe.diarize.pyannote")

_TORCH_LOAD_PATCHED = False


def _patch_torch_load() -> None:
    """torch 2.6+ zet torch.load(weights_only=True) als default; pyannote's checkpoints bevatten
    globals (bv. TorchVersion) die dan niet geladen worden -> UnpicklingError. Deze worker draait
    UITSLUITEND op de gated pyannote-modellen die we zelf met ons token downloaden (vertrouwde
    bron), dus forceren we de volledige load. Eenmalig, idempotent."""
    global _TORCH_LOAD_PATCHED
    if _TORCH_LOAD_PATCHED:
        return
    import torch

    _orig_load = torch.load

    def _full_load(*args, **kwargs):
        kwargs["weights_only"] = False   # forceren: lightning/pyannote geven soms True expliciet mee
        return _orig_load(*args, **kwargs)

    torch.load = _full_load
    _TORCH_LOAD_PATCHED = True


def _load_waveform(path: str):
    """Lees een 16-bit PCM wav met de stdlib -> (waveform (ch, samples) float32 tensor, sample_rate).
    Zo hoeft pyannote het bestand niet zelf te decoderen (omzeilt torchcodec/FFmpeg in 4.x)."""
    import wave

    import numpy as np
    import torch

    with wave.open(path, "rb") as w:
        n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
    data = data.reshape(-1, ch).T if ch > 1 else data[None, :]
    return torch.from_numpy(data.copy()), sr


def _to_annotation(result, exclusive: bool = False):
    """Haal de spreker-Annotation uit het pipeline-resultaat.

    - pyannote 3.x: `result` IS al een Annotation (heeft itertracks()).
    - pyannote 4.x: `result` is een DiarizeOutput met .speaker_diarization en
      .exclusive_speaker_diarization. Bij exclusive=True gebruiken we die laatste.
    Puur/duck-typed -> testbaar zonder pyannote.
    """
    if hasattr(result, "itertracks"):
        return result
    if exclusive:
        ex = getattr(result, "exclusive_speaker_diarization", None)
        if ex is not None:
            return ex
    return getattr(result, "speaker_diarization", None) or getattr(result, "exclusive_speaker_diarization", None)


class PyannoteDiarizeBackend(DiarizeBackend):
    name = "pyannote"

    def __init__(self, model: str, hf_token: str, device: str, exclusive: bool = False):
        self._model_name = model
        self._hf_token = hf_token or None
        self._device = device
        self._exclusive = exclusive
        self._pipeline = None

    def load(self) -> None:
        if self._pipeline is not None:
            return
        import torch
        # We voeren de golfvorm zelf in (stdlib wave), dus torchcodec is niet nodig; onderdruk de
        # luidruchtige "torchcodec is not installed correctly"-waarschuwing die pyannote 4 bij import geeft.
        import warnings
        warnings.filterwarnings("ignore", message=".*torchcodec.*")
        from pyannote.audio import Pipeline

        _patch_torch_load()
        log.info("pyannote laden: model=%s device=%s exclusive=%s",
                 self._model_name, self._device, self._exclusive)
        # 3.x gebruikt use_auth_token=, 4.x gebruikt token= (use_auth_token verwijderd -> TypeError).
        try:
            self._pipeline = Pipeline.from_pretrained(self._model_name, use_auth_token=self._hf_token)
        except TypeError:
            self._pipeline = Pipeline.from_pretrained(self._model_name, token=self._hf_token)
        if self._pipeline is None:  # gated model zonder (geldig) token geeft None terug
            raise RuntimeError(
                "pyannote-pipeline kon niet worden geladen — controleer DIARIZE_HF_TOKEN "
                "en of de modelvoorwaarden op HuggingFace zijn geaccepteerd."
            )
        if self._device.startswith("cuda"):
            self._pipeline.to(torch.device("cuda"))

    def diarize(
        self, wav_path: str, min_speakers: int | None = None, max_speakers: int | None = None
    ) -> list[SpeakerTurn]:
        self.load()
        params: dict = {}
        if min_speakers:
            params["min_speakers"] = int(min_speakers)
        if max_speakers:
            params["max_speakers"] = int(max_speakers)
        # Golfvorm zelf invoeren (geen torchcodec-decoding).
        waveform, sr = _load_waveform(wav_path)
        result = self._pipeline({"waveform": waveform, "sample_rate": sr}, **params)
        annotation = _to_annotation(result, exclusive=self._exclusive)
        if annotation is None:
            raise RuntimeError("Onverwacht pyannote-resultaat: geen speaker-diarization gevonden.")
        turns: list[SpeakerTurn] = []
        for segment, _track, speaker in annotation.itertracks(yield_label=True):
            turns.append(SpeakerTurn(start=float(segment.start), end=float(segment.end), speaker=str(speaker)))
        return turns
