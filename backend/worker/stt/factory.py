"""Kies de STT-backend op basis van env (STT_BACKEND)."""
from __future__ import annotations

from app.config import get_settings

from .base import STTBackend
from .faster_whisper_backend import FasterWhisperBackend

_instance: STTBackend | None = None


def get_backend() -> STTBackend:
    """Singleton: model wordt één keer per worker geladen."""
    global _instance
    if _instance is not None:
        return _instance

    s = get_settings()
    if s.stt_backend == "canary":
        # Lazy import: de default-image heeft geen NeMo/torch (losgekoppeld).
        from .canary_backend import CanaryBackend

        _instance = CanaryBackend(
            model=s.stt_model, device=s.stt_device, compute_type=s.stt_compute_type,
            load_timestamps_model=s.stt_word_timestamps,
        )
    elif s.stt_backend == "faster_whisper":
        _instance = FasterWhisperBackend(
            model=s.stt_model, device=s.stt_device, compute_type=s.stt_compute_type
        )
    elif s.stt_backend == "openai":
        from .openai_backend import OpenAISTTBackend

        _instance = OpenAISTTBackend(
            base_url=s.stt_openai_base_url, model=s.stt_model,
            api_key=s.stt_openai_api_key, timeout=s.stt_openai_timeout_seconds,
        )
    else:
        raise ValueError(f"Onbekende STT_BACKEND: {s.stt_backend!r}")
    return _instance
