"""Kies de diarisatie-backend op basis van env (DIARIZE_BACKEND)."""
from __future__ import annotations

from app.config import get_settings

from .base import DiarizeBackend
from .none_backend import NoneDiarizeBackend

_instance: DiarizeBackend | None = None


def get_diarize_backend() -> DiarizeBackend:
    """Singleton: model wordt één keer per worker geladen."""
    global _instance
    if _instance is not None:
        return _instance

    s = get_settings()
    if s.diarize_backend == "none":
        _instance = NoneDiarizeBackend()
    elif s.diarize_backend == "pyannote":
        # Lazy import: torch/pyannote alleen als deze backend echt gekozen is.
        from .pyannote_backend import PyannoteDiarizeBackend

        _instance = PyannoteDiarizeBackend(
            model=s.diarize_model, hf_token=s.diarize_hf_token, device=s.diarize_device,
            exclusive=s.diarize_exclusive,
        )
    else:
        raise ValueError(f"Onbekende DIARIZE_BACKEND: {s.diarize_backend!r}")
    return _instance
