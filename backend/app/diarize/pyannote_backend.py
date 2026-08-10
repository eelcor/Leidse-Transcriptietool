"""pyannote.audio-diarisatiebackend (opt-in, DIARIZE_BACKEND=pyannote).

Zwaar (torch + gated modellen): alle imports zijn lazy in load(), zodat dit bestand in de
API/basis-worker geïmporteerd kan worden zonder torch/pyannote binnen te halen. Draait in de
aparte diarize-worker (zie backend/worker/diarize_worker.py + docker-compose).

Kaart-pinning: binnen de container is de toegewezen GPU altijd cuda:0 (via CUDA_VISIBLE_DEVICES);
DIARIZE_DEVICE=cuda gebruikt dus cuda:0. Zie deploy/DEPLOY.md.
"""
from __future__ import annotations

import logging

from .base import DiarizeBackend, SpeakerTurn

log = logging.getLogger("transcribe.diarize.pyannote")

_TORCH_LOAD_PATCHED = False


def _patch_torch_load() -> None:
    """torch 2.6 zet torch.load(weights_only=True) als default; pyannote's checkpoints bevatten
    globals (bv. TorchVersion) die dan niet geladen worden -> UnpicklingError. Deze worker draait
    UITSLUITEND op de gated pyannote-modellen die we zelf met ons token downloaden (vertrouwde
    bron), dus forceren we de volledige load. Eenmalig, idempotent."""
    global _TORCH_LOAD_PATCHED
    if _TORCH_LOAD_PATCHED:
        return
    import torch

    _orig_load = torch.load

    def _full_load(*args, **kwargs):
        # Forceren (niet setdefault): lightning/pyannote geven soms weights_only=True expliciet mee.
        kwargs["weights_only"] = False
        return _orig_load(*args, **kwargs)

    torch.load = _full_load
    _TORCH_LOAD_PATCHED = True


class PyannoteDiarizeBackend(DiarizeBackend):
    name = "pyannote"

    def __init__(self, model: str, hf_token: str, device: str):
        self._model_name = model
        self._hf_token = hf_token or None
        self._device = device
        self._pipeline = None

    def load(self) -> None:
        if self._pipeline is not None:
            return
        import torch
        from pyannote.audio import Pipeline

        _patch_torch_load()
        log.info("pyannote laden: model=%s device=%s", self._model_name, self._device)
        self._pipeline = Pipeline.from_pretrained(self._model_name, use_auth_token=self._hf_token)
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
        annotation = self._pipeline(wav_path, **params)
        turns: list[SpeakerTurn] = []
        for segment, _track, speaker in annotation.itertracks(yield_label=True):
            turns.append(SpeakerTurn(start=float(segment.start), end=float(segment.end), speaker=str(speaker)))
        return turns
