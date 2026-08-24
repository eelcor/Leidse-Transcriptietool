"""Verbinding met de arq/Redis-wachtrij vanuit de API.

De API zet enkel jobs op de queue; de worker (backend/worker) verwerkt ze.
Dit ontkoppelt de webrequest van de zware STT/LLM-verwerking en is de
schaalbaarheids-as: meer volume = meer workers.
"""
from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from .config import get_settings

# Sprekerdiarisatie draait op een EIGEN queue, verwerkt door een aparte worker met
# torch/pyannote (de basis-worker blijft licht). Zie backend/worker/diarize_worker.py.
DIARIZE_QUEUE = "arq:queue:diarize"

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def enqueue_transcription(session_id: str) -> None:
    pool = await get_pool()
    await pool.enqueue_job("transcribe_session", session_id, _job_id=f"stt:{session_id}")


async def enqueue_report(report_id: str) -> None:
    pool = await get_pool()
    await pool.enqueue_job("generate_report", report_id, _job_id=f"report:{report_id}")


async def enqueue_diarization(session_id: str, diar_id: str) -> None:
    pool = await get_pool()
    await pool.enqueue_job(
        "diarize_session", session_id, diar_id,
        _queue_name=DIARIZE_QUEUE, _job_id=f"diarize:{diar_id}",   # uniek per rij (ook bij opnieuw indelen)
    )
