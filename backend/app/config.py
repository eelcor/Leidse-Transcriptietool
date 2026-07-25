"""Centrale configuratie, volledig via env-vars (12-factor).

Alle instelbare gedrag (modelnamen, endpoints, bewaartermijn, maxgrootte,
STT-device/precisie) staat hier, zodat dev en prod alleen via de omgeving
verschillen. Geen geheimen of persoonsgegevens hardcoderen.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Infrastructuur ---
    database_url: str = "postgresql+asyncpg://transcribe:transcribe@db:5432/transcribe"
    redis_url: str = "redis://redis:6379/0"
    storage_dir: str = "/data"

    # --- Uploadlimieten ---
    max_upload_mb: int = 200
    default_language: str = "nl"
    # ASR-audio-optimalisatie (hoogdoorlaat + loudness-normalisatie) standaard aan.
    audio_optimize_default: bool = True

    # --- Bewaartermijn ---
    # Aantal WERKdagen ná afronden van de verwerking (weekenden tellen niet mee).
    retention_workdays: int = 2
    cleanup_interval_seconds: int = 3600

    # --- STT (spraak-naar-tekst) ---
    # "faster_whisper" (default) | "canary" (NeMo) | "openai" (extern STT-endpoint).
    stt_backend: str = "faster_whisper"
    # faster_whisper: b.v. "large-v2"; canary: b.v. "nvidia/canary-1b-v2"
    stt_model: str = "large-v2"
    stt_device: str = "cpu"          # "cpu" | "cuda"  (CPU-fallback werkt altijd)
    stt_compute_type: str = "int8"   # faster-whisper: int8 | int8_float16 | float16 | float32
    stt_concurrency: int = 1         # max gelijktijdige STT-jobs (VRAM-bescherming)
    stt_word_timestamps: bool = True

    # --- STT via extern OpenAI-compatibel endpoint (STT_BACKEND=openai) ---
    # Bv. whisper.cpp-server of een faster-whisper OpenAI-wrapper. De worker heeft
    # dan zelf geen STT-model/torch nodig (STT_MODEL = de modelnaam die dat endpoint verwacht).
    stt_openai_base_url: str = "http://host.docker.internal:8035/v1"
    stt_openai_api_key: str = "not-needed"
    stt_openai_timeout_seconds: int = 600

    # --- Verslag-LLM (bestaand OpenAI-compatibel endpoint, NIET zelf hosten) ---
    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "qwen3.6-27b"
    llm_api_key: str = "not-needed"
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 600

    # Pad naar PROMPTS.md (letterlijke prompt-teksten, single source of truth).
    prompts_file: str = "/app/PROMPTS.md"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
