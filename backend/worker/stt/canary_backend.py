"""NVIDIA Canary 1B v2 backend via de NeMo-toolkit (vastgelegde keuze).

- Ondersteunt Nederlands (25 EU-talen), CC-BY-4.0, ~978M params.
- Doet automatisch long-form chunking (1s overlap boven ~40s) — geen eigen segmentatie nodig.
- Input is 16kHz mono wav/flac (de worker levert dat via ffmpeg aan).

NeMo wordt lazy geïmporteerd zodat de rest van de app (en de faster-whisper-modus)
niet afhankelijk is van een zware NeMo-installatie.
"""
from __future__ import annotations

import logging
import os

from .base import Segment, STTBackend, TranscriptResult

log = logging.getLogger("transcribe.stt.canary")


class CanaryBackend(STTBackend):
    name = "canary"

    # STT_COMPUTE_TYPE-waarden die als half precision (fp16) tellen.
    _FP16 = {"float16", "fp16", "half"}

    def __init__(self, model: str, device: str, compute_type: str = "float32",
                 load_timestamps_model: bool = True):
        # model bijv. "nvidia/canary-1b-v2"
        self._model_name = model
        self._device = device
        self._compute_type = (compute_type or "float32").lower()
        # Canary-1b-v2 laadt standaard een intern timestamps-model (~2-3GB fp32).
        # Zet dit uit (via STT_WORD_TIMESTAMPS=false) om VRAM te besparen; dan
        # produceert de backend geen timestamps maar past het model op krappe GPU's.
        self._load_timestamps_model = load_timestamps_model
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return

        # CPU-modus: verberg alle GPU's vóór torch/NeMo importeert. Anders laadt
        # NeMo (o.a. Canary's interne timestamps-model) alsnog op een GPU die door
        # Qwen bezet is -> CUDA OOM. Dit garandeert een werkende CPU-fallback.
        if not self._device.startswith("cuda"):
            os.environ["CUDA_VISIBLE_DEVICES"] = ""

        import torch  # noqa: F401

        log.info("Canary/NeMo laden: model=%s device=%s compute=%s",
                 self._model_name, self._device, self._compute_type)

        # ALTIJD eerst op CPU laden (map_location='cpu'). Canary laadt naast het
        # hoofdmodel een intern timestamps-model; direct fp32 op een GPU met weinig
        # vrije ruimte (V100 die Qwen deelt) knalt anders al tijdens het laden OOM.
        # Daarna pas — optioneel in fp16 — naar de GPU verplaatsen.
        model = self._load_pretrained()
        if self._device.startswith("cuda"):
            try:
                if self._compute_type in self._FP16:
                    model = model.half()  # halveert de VRAM-footprint
                model = model.to(self._device)
            except Exception as exc:  # pragma: no cover - hardware-afhankelijk
                log.warning("Canary naar %s verplaatsen mislukt (%s); blijf op CPU.",
                            self._device, exc)
        model.eval()
        self._model = model

    def _load_pretrained(self):
        """Laad het pretrained model op CPU (map_location='cpu').

        Canary is een multitask-model (EncDecMultiTaskModel); de generieke
        ASRModel.from_pretrained kan die abstracte basisklasse in sommige
        NeMo-versies niet instantiëren. We proberen daarom eerst de generieke
        loader (werkt voor CTC/RNNT-modellen) en vallen terug op de
        multitask-klasse (Canary).

        Als timestamps uit staan, laden we met config-override
        `restore_timestamps_model=False`, zodat het interne timestamps-model niet
        wordt geladen (~2-3GB VRAM minder).
        """
        from nemo.collections.asr.models import ASRModel

        if self._load_timestamps_model:
            try:
                return ASRModel.from_pretrained(model_name=self._model_name, map_location="cpu")
            except TypeError as exc:
                log.info("Generieke ASRModel-loader faalde (%s); probeer EncDecMultiTaskModel.", exc)
                from nemo.collections.asr.models import EncDecMultiTaskModel

                return EncDecMultiTaskModel.from_pretrained(model_name=self._model_name, map_location="cpu")

        # Zonder timestamps-model: config ophalen, vlag uitzetten, herstellen.
        import tempfile

        from nemo.collections.asr.models import EncDecMultiTaskModel
        from omegaconf import OmegaConf

        log.info("Canary laden ZONDER intern timestamps-model (bespaart VRAM; geen timestamps).")
        cfg = ASRModel.from_pretrained(model_name=self._model_name, return_config=True)
        OmegaConf.set_struct(cfg, False)
        cfg.restore_timestamps_model = False
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            OmegaConf.save(cfg, f.name)
            override = f.name
        return EncDecMultiTaskModel.from_pretrained(
            model_name=self._model_name, override_config_path=override, map_location="cpu"
        )

    def transcribe(self, wav_path: str, language: str, word_timestamps: bool,
                   hotwords: str | None = None, on_segment=None) -> TranscriptResult:
        # hotwords/biasing én on_segment (voortgang): Canary levert in één keer -> genegeerd.
        self.load()
        # Timestamps alleen mogelijk als het interne timestamps-model geladen is.
        want_ts = word_timestamps and self._load_timestamps_model
        # NeMo Canary: source/target taal instelbaar; timestamps optioneel.
        kwargs = {"batch_size": 1}
        try:
            results = self._model.transcribe(
                [wav_path],
                timestamps=want_ts,
                source_lang=language or "nl",
                target_lang=language or "nl",
                **kwargs,
            )
        except TypeError:
            # Oudere/andere NeMo-signatuur zonder taal/timestamp-kwargs.
            results = self._model.transcribe([wav_path], **kwargs)

        return _to_result(results, want_ts)


def _to_result(results, word_timestamps: bool) -> TranscriptResult:
    """Normaliseer de uiteenlopende NeMo-returnvormen naar TranscriptResult."""
    if not results:
        return TranscriptResult(text="", segments=[])
    item = results[0]

    # Nieuwere NeMo geeft Hypothesis-objecten met .text en .timestamp.
    text = getattr(item, "text", None)
    segments: list[Segment] = []
    if word_timestamps:
        ts = getattr(item, "timestamp", None)
        if isinstance(ts, dict):
            level = ts.get("segment") or ts.get("word") or []
            for e in level:
                segments.append(
                    Segment(
                        start=e.get("start"),
                        end=e.get("end"),
                        text=(e.get("segment") or e.get("word") or "").strip(),
                    )
                )

    if text is None:
        text = item if isinstance(item, str) else str(item)
    return TranscriptResult(text=text.strip(), segments=segments)
