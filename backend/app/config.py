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
    # Max gelijktijdige LLM-verslagen. Het LLM-endpoint is doorgaans effectief 1 slot,
    # dus 1: overige verslagen blijven netjes 'queued' met een wachtrij-positie.
    llm_concurrency: int = 1
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
    # "Thinking"/reasoning UIT voor verslagen. Reasoning-modellen (Qwen3) stoppen anders een groot
    # <think>-blok vóór het antwoord; op een lang transcript loopt dat ver over de timeout heen.
    # We geven dit per request mee als chat_template_kwargs.enable_thinking (llama.cpp met --jinja).
    # Zet LLM_ENABLE_THINKING=true als je het endpoint tóch wilt laten redeneren.
    llm_enable_thinking: bool = False
    # Geen "timeout"-mislukking als het LLM-endpoint traag/bezet is: de call wacht
    # desnoods lang (max ~1 dag) tot het endpoint 'm bedient. Bij een druk gedeeld
    # endpoint komt het verslag zo alsnog door i.p.v. te falen. (Env-instelbaar.)
    llm_timeout_seconds: int = 86400

    # Pad naar PROMPTS.md (letterlijke prompt-teksten, single source of truth).
    prompts_file: str = "/app/PROMPTS.md"

    # --- Beveiliging ---
    # Swagger-UI en OpenAPI-schema standaard UIT in productie (kleiner aanvalsoppervlak;
    # het schema somt anders alle endpoints op). Zet EXPOSE_API_DOCS=true voor lokaal debuggen.
    expose_api_docs: bool = False

    # --- Diarisatie (sprekerlabels) — optioneel, standaard UIT (DIARIZE_BACKEND=none) ---
    # Optionele spreker-diarisatie (pyannote) die ná STT sprekerlabels toewijst. Draait als
    # aparte job op een eigen queue/worker, zodat torch/pyannote uit de basis-worker blijven.
    # 'none' (default) = geen enkel gedragsverschil met de niet-diarisatie-opstelling.
    diarize_backend: str = "none"                # "none" | "pyannote"
    diarize_model: str = "pyannote/speaker-diarization-3.1"
    diarize_device: str = "cuda"                 # "cuda" | "cpu"
    diarize_compute_type: str = "float16"        # gereserveerd voor backends met een precisiekeuze
    diarize_hf_token: str = ""                   # HuggingFace-token voor de gated pyannote-modellen
    diarize_concurrency: int = 1                 # max gelijktijdige diarisatie-jobs (VRAM-bescherming)
    # Alleen bij community-1 (pyannote 4.x): 'exclusive' toewijzing (elk moment één spreker) i.p.v.
    # de standaard speaker-diarization. Vereenvoudigt de merge; genegeerd door 3.x.
    diarize_exclusive: bool = False
    # Merge-parameters (fase 3): gaten < min_gap binnen dezelfde spreker dichtplakken;
    # sprekerfragmenten < min_segment weggooien en aan de omliggende spreker toekennen.
    diarize_min_gap: float = 0.5
    diarize_min_segment: float = 0.5
    # Namen: 'placeholder' = LLM én DB zien alleen SPREKER_A/B/C; namen leven client-side.
    # 'direct' = ingevulde namen gaan mee in de LLM-context en komen in het verslag (dus in de DB).
    speaker_names_mode: str = "placeholder"      # "placeholder" | "direct"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
