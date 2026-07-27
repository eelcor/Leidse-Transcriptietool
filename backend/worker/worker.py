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
import os
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Report, ReportStatus, Session, SessionStatus
from app.prompts import build_messages
from app.tokens import new_token
from app.workdays import compute_expires_at
from app import stats, storage

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
                await stats.record_event(db, "failed", target="transcribe")
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

        # Vooraf gevraagd verslag? Maak de report-rij en zet 'm meteen op de queue,
        # zodat transcriptie -> LLM in één keer wordt ingepland (geen handmatige trigger).
        # Anoniem statistiek-event.
        started = obj.processing_started_at or finished
        try:
            wav_bytes = os.path.getsize(storage.wav_path(session_id))
            audio_seconds = max(0.0, (wav_bytes - 44) / 32000.0)  # 16kHz mono 16-bit
        except OSError:
            audio_seconds = None
        await stats.record_event(
            db, "transcribed",
            duration_seconds=(finished - started).total_seconds(),
            audio_seconds=audio_seconds,
            words=len((result.text or "").split()),
            language=obj.language, source=obj.source,
            audio_format=obj.audio_format, audio_bytes=obj.audio_bytes,
        )

        auto = obj.auto_report
        auto_report_id = None
        if auto:
            auto_report_id = new_token()
            db.add(Report(
                id=auto_report_id,
                session_id=session_id,
                kinds=auto.get("kinds"),
                custom_prompt=auto.get("custom_prompt"),
                context=auto.get("context"),
                status=ReportStatus.QUEUED,
                created_at=finished,
                updated_at=finished,
            ))
        await db.commit()

    if auto_report_id is not None:
        redis = ctx.get("redis")
        if redis is not None:
            await redis.enqueue_job("generate_report", auto_report_id, _job_id=f"report:{auto_report_id}")
        log.info("Auto-verslag ingepland voor sessie %s.", session_id[:8])
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

    report_started = _now()
    try:
        messages = build_messages(transcript, kinds, custom, context)
        content = await llm.generate(messages)
    except Exception as exc:
        log.exception("Verslag genereren mislukt voor %s", report_id[:8])
        async with maker() as db:
            await stats.record_event(db, "failed", target="report")
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
        await stats.record_event(
            db, "report",
            duration_seconds=(_now() - report_started).total_seconds(),
            report_mode=stats.report_mode_from_report(kinds, custom),
        )
        await db.commit()
    return "ok"


# --------------------------------------------------------------------------
# arq WorkerSettings
# --------------------------------------------------------------------------
async def _recover_stuck_transcriptions(ctx: dict) -> None:
    """Sessies die op 'transcribing' bleven hangen (worker onderbroken door herstart/crash)
    opnieuw inplannen. Zo overleeft een lange opname een update of herstart."""
    maker = get_sessionmaker()
    async with maker() as db:
        stuck = (
            await db.execute(select(Session).where(Session.status == SessionStatus.TRANSCRIBING))
        ).scalars().all()
        ids = [s.id for s in stuck]
    if not ids:
        return
    redis = ctx.get("redis")
    if redis is None:
        from app.queue import get_pool
        redis = await get_pool()
    for sid in ids:
        jid = f"stt:{sid}"
        # Stale arq-status opruimen zodat de job niet gededupliceerd/geblokkeerd wordt.
        for key in (f"arq:in-progress:{jid}", f"arq:retry:{jid}", f"arq:job:{jid}", f"arq:result:{jid}"):
            try:
                await redis.delete(key)
            except Exception:
                pass
        try:
            await redis.zrem("arq:queue", jid)
            await redis.enqueue_job("transcribe_session", sid, _job_id=jid)
            log.warning("Onderbroken transcriptie opnieuw ingepland: %s", sid[:12])
        except Exception:
            log.exception("Kon onderbroken transcriptie niet opnieuw inplannen: %s", sid[:12])
    log.warning("%d onderbroken transcriptie(s) hersteld bij worker-start.", len(ids))


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["stt_semaphore"] = asyncio.Semaphore(settings.stt_concurrency)
    log.info("Worker gestart: STT_BACKEND=%s concurrency=%s", settings.stt_backend, settings.stt_concurrency)
    # Model warm laden zodat de eerste job niet de laadtijd betaalt.
    try:
        get_backend().load()
    except Exception:
        log.exception("Model warm laden mislukt; wordt bij de eerste job opnieuw geprobeerd.")
    # Robuustheid: onderbroken transcripties opnieuw inplannen (overleeft update/herstart).
    try:
        await _recover_stuck_transcriptions(ctx)
    except Exception:
        log.exception("Herstel van onderbroken transcripties mislukt.")


from app.queue import redis_settings as _redis_settings  # noqa: E402


class WorkerSettings:
    """arq leest deze klasse-attributen bij het starten van de worker."""

    functions = [transcribe_session, generate_report]
    on_startup = startup
    redis_settings = _redis_settings()
    max_tries = 3            # retry met backoff bij transiente fouten
    job_timeout = 3600       # lange opnames toegestaan
    keep_result = 3600
