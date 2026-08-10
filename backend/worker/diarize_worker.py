"""Aparte arq-worker voor sprekerdiarisatie, op een EIGEN queue (DIARIZE_QUEUE).

De basis-worker (STT/LLM) blijft bewust torch-vrij; deze worker heeft torch + pyannote
(aparte image, zie backend/Dockerfile.diarize + docker-compose). Draai gepind op één GPU via
CUDA_VISIBLE_DEVICES; binnen de container is dat altijd cuda:0.

Dunne wrapper rond app.diarize.run.run_diarization (die zonder queue/GPU getest wordt).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext

from app.config import get_settings
from app.db import get_sessionmaker
from app.diarize.factory import get_diarize_backend
from app.diarize.run import run_diarization
from app.queue import DIARIZE_QUEUE
from app.queue import redis_settings as _redis_settings

log = logging.getLogger("transcribe.diarize.worker")


async def diarize_session(ctx: dict, session_id: str, diar_id: str) -> str:
    """Verwerk één diarisatie-job. Faalt zacht (run_diarization werpt niets)."""
    maker = get_sessionmaker()
    sem = ctx.get("diarize_semaphore")
    backend = get_diarize_backend()
    async with (sem or nullcontext()):  # begrens gelijktijdige diarisatie (VRAM-bescherming)
        return await run_diarization(maker, session_id, diar_id, backend)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["diarize_semaphore"] = asyncio.Semaphore(settings.diarize_concurrency)
    log.info("Diarize-worker gestart: DIARIZE_BACKEND=%s concurrency=%s",
             settings.diarize_backend, settings.diarize_concurrency)
    # Model warm laden zodat de eerste job niet de laadtijd betaalt.
    try:
        get_diarize_backend().load()
    except Exception:
        log.exception("Diarisatiemodel warm laden mislukt; wordt bij de eerste job opnieuw geprobeerd.")


class DiarizeWorkerSettings:
    """arq-worker die ALLEEN de diarize-queue verwerkt."""

    functions = [diarize_session]
    on_startup = startup
    queue_name = DIARIZE_QUEUE
    redis_settings = _redis_settings()
    max_tries = 2
    job_timeout = 86400
    keep_result = 3600
