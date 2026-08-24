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
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.diarize.factory import get_diarize_backend
from app.diarize.run import run_diarization
from app.models import Diarization, DiarizationStatus
from app.queue import DIARIZE_QUEUE, enqueue_report
from app.queue import redis_settings as _redis_settings

log = logging.getLogger("transcribe.diarize.worker")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _enqueue_auto_report(diar_id: str) -> None:
    """Plan het (vooraf gevraagde) verslag in ná de diarisatie, zodat het sprekerlabels heeft.
    Wordt ook bij een MISLUKTE diarisatie aangeroepen: het verslag draait dan zonder labels."""
    maker = get_sessionmaker()
    async with maker() as db:
        diar = await db.get(Diarization, diar_id)
        rid = diar.auto_report_id if diar else None
    if rid:
        await enqueue_report(rid)


async def diarize_session(ctx: dict, session_id: str, diar_id: str) -> str:
    """Verwerk één diarisatie-job. Faalt zacht (run_diarization werpt niets)."""
    maker = get_sessionmaker()
    sem = ctx.get("diarize_semaphore")
    backend = get_diarize_backend()
    async with (sem or nullcontext()):  # begrens gelijktijdige diarisatie (VRAM-bescherming)
        result = await run_diarization(maker, session_id, diar_id, backend)
    # Ongeacht de uitkomst: het (vooraf gevraagde) verslag alsnog inplannen.
    await _enqueue_auto_report(diar_id)
    return result


async def _recover_stuck_diarizations(ctx: dict) -> None:
    """Diarisaties die op 'running' bleven hangen (worker onderbroken door herstart/crash)
    opnieuw inplannen. Analoog aan de STT-/verslag-herstelhooks; idempotent."""
    maker = get_sessionmaker()
    async with maker() as db:
        stuck = (await db.execute(
            select(Diarization).where(Diarization.status == DiarizationStatus.RUNNING)
        )).scalars().all()
        pairs = [(d.session_id, d.id) for d in stuck]
        for d in stuck:
            d.status = DiarizationStatus.QUEUED
            d.updated_at = _now()
        if pairs:
            await db.commit()
    if not pairs:
        return
    redis = ctx.get("redis")
    if redis is None:
        from app.queue import get_pool
        redis = await get_pool()
    for sid, did in pairs:
        jid = f"diarize:{did}"
        for key in (f"arq:in-progress:{jid}", f"arq:retry:{jid}", f"arq:job:{jid}", f"arq:result:{jid}"):
            try:
                await redis.delete(key)
            except Exception:
                pass
        try:
            await redis.zrem(DIARIZE_QUEUE, jid)
            await redis.enqueue_job("diarize_session", sid, did, _queue_name=DIARIZE_QUEUE, _job_id=jid)
            log.warning("Onderbroken diarisatie opnieuw ingepland: %s", did[:12])
        except Exception:
            log.exception("Kon onderbroken diarisatie niet opnieuw inplannen: %s", did[:12])
    log.warning("%d onderbroken diarisatie(s) hersteld bij worker-start.", len(pairs))


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
    try:
        await _recover_stuck_diarizations(ctx)
    except Exception:
        log.exception("Herstel van onderbroken diarisaties mislukt.")


class DiarizeWorkerSettings:
    """arq-worker die ALLEEN de diarize-queue verwerkt."""

    functions = [diarize_session]
    on_startup = startup
    queue_name = DIARIZE_QUEUE
    redis_settings = _redis_settings()
    max_tries = 2
    job_timeout = 86400
    keep_result = 3600
