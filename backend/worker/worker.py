"""arq-worker: verwerkt STT- en LLM-jobs van de wachtrij.

- transcribe_session: ffmpeg-resample -> STT-backend -> transcript + timestamps.
  Begrensd door een semafoor (STT_CONCURRENCY) zodat piek-VRAM voorspelbaar blijft
  en het bestaande Qwen-model niet uit het geheugen wordt gedrukt.
- generate_report: bouwt messages uit PROMPTS.md en roept het Qwen-endpoint aan.

Zware, blokkerende STT draait in een thread-executor; de LLM-call is async I/O.
Retries/backoff worden door arq geregeld (zie WorkerSettings).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Report, ReportStatus, Session, SessionStatus
from app.prompts import build_messages
from app.workdays import compute_expires_at
from app import storage

from . import audio, llm
from .stt.factory import get_backend

log = logging.getLogger("transcribe.worker")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# STT-job
# --------------------------------------------------------------------------
async def transcribe_session(ctx: dict, session_id: str) -> str:
    maker = get_sessionmaker()
    settings = get_settings()

    async with maker() as db:
        obj = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
        if obj is None:
            log.info("Sessie %s bestaat niet (meer); job overgeslagen.", session_id[:8])
            return "gone"
        # Idempotent: al klaar? niets doen.
        if obj.status == SessionStatus.TRANSCRIBED:
            return "already-done"
        obj.status = SessionStatus.TRANSCRIBING
        obj.processing_started_at = _now()
        obj.updated_at = _now()
        raw_path = obj.audio_path
        language = obj.language
        optimize = obj.optimize_audio
        await db.commit()

    try:
        wav = storage.wav_path(session_id)
        audio.resample_to_wav(raw_path, wav, optimize=optimize)

        backend = get_backend()
        sem: asyncio.Semaphore = ctx["stt_semaphore"]
        loop = asyncio.get_running_loop()
        async with sem:  # begrens gelijktijdige STT-jobs (VRAM-bescherming)
            result = await loop.run_in_executor(
                None,
                lambda: backend.transcribe(str(wav), language, settings.stt_word_timestamps),
            )
    except Exception as exc:
        log.exception("STT mislukt voor sessie %s", session_id[:8])
        async with maker() as db:
            obj = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
            if obj is not None:
                obj.status = SessionStatus.FAILED
                obj.error = f"Transcriptie mislukt: {type(exc).__name__}"
                obj.updated_at = _now()
                await db.commit()
        raise  # laat arq retry/backoff doen

    finished = _now()
    expires = compute_expires_at(finished, settings.retention_workdays)
    async with maker() as db:
        obj = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
        if obj is None:
            return "gone"
        obj.transcript = result.text
        obj.segments = result.segments_as_dicts() if settings.stt_word_timestamps else None
        obj.stt_backend = backend.name
        obj.status = SessionStatus.TRANSCRIBED
        obj.processing_finished_at = finished
        # Bewaartermijn pas NU vastzetten (2 werkdagen ná verwerking).
        obj.expires_at = expires
        obj.updated_at = finished
        await db.commit()
    log.info("Sessie %s getranscribeerd (verloopt %s).", session_id[:8], expires.isoformat())
    return "ok"


# --------------------------------------------------------------------------
# LLM-verslag-job
# --------------------------------------------------------------------------
async def generate_report(ctx: dict, report_id: str) -> str:
    maker = get_sessionmaker()
    async with maker() as db:
        r = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
        if r is None:
            return "gone"
        if r.status == ReportStatus.DONE:
            return "already-done"
        sess = (await db.execute(select(Session).where(Session.id == r.session_id))).scalar_one_or_none()
        if sess is None or not sess.transcript:
            r.status = ReportStatus.FAILED
            r.error = "Transcript niet beschikbaar."
            r.updated_at = _now()
            await db.commit()
            return "no-transcript"
        r.status = ReportStatus.RUNNING
        r.updated_at = _now()
        transcript = sess.transcript
        kinds, custom, context = r.kinds, r.custom_prompt, r.context
        await db.commit()

    try:
        messages = build_messages(transcript, kinds, custom, context)
        content = await llm.generate(messages)
    except Exception as exc:
        log.exception("Verslag genereren mislukt voor %s", report_id[:8])
        async with maker() as db:
            r = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
            if r is not None:
                r.status = ReportStatus.FAILED
                r.error = f"Verslag mislukt: {type(exc).__name__}"
                r.updated_at = _now()
                await db.commit()
        raise

    async with maker() as db:
        r = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
        if r is None:
            return "gone"
        r.content = content
        r.status = ReportStatus.DONE
        r.updated_at = _now()
        await db.commit()
    return "ok"


# --------------------------------------------------------------------------
# arq WorkerSettings
# --------------------------------------------------------------------------
async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["stt_semaphore"] = asyncio.Semaphore(settings.stt_concurrency)
    log.info("Worker gestart: STT_BACKEND=%s concurrency=%s", settings.stt_backend, settings.stt_concurrency)
    # Model warm laden zodat de eerste job niet de laadtijd betaalt.
    try:
        get_backend().load()
    except Exception:
        log.exception("Model warm laden mislukt; wordt bij de eerste job opnieuw geprobeerd.")


from app.queue import redis_settings as _redis_settings  # noqa: E402


class WorkerSettings:
    """arq leest deze klasse-attributen bij het starten van de worker."""

    functions = [transcribe_session, generate_report]
    on_startup = startup
    redis_settings = _redis_settings()
    max_tries = 3            # retry met backoff bij transiente fouten
    job_timeout = 3600       # lange opnames toegestaan
    keep_result = 3600
