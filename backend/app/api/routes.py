"""Alle HTTP-endpoints.

Ontwerp-uitgangspunten:
- De sessie-id (hoge-entropie token) is de enige toegangssleutel; wie hem heeft,
  mag de data zien. Er is geen login (anoniem gebruik).
- Minimale logging; nooit transcript-inhoud loggen.
- Zware verwerking gaat via de wachtrij, niet in de request.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import prompts, queue, stats, storage
from ..config import get_settings
from ..db import get_db
from ..models import Report, ReportStatus, Session, SessionStatus
from ..schemas import (
    CreateReportRequest,
    CreateSessionResponse,
    FeedbackRequest,
    ReportOut,
    SegmentOut,
    SessionResultOut,
    SessionStatusOut,
    UpdateReportRequest,
)
from ..tokens import new_token

router = APIRouter(prefix="/api")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audio_format(filename: str | None, mime: str | None) -> str | None:
    """Korte, niet-herleidbare formaat-aanduiding (extensie of mime-subtype)."""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if 1 <= len(ext) <= 8 and ext.isalnum():
            return ext
    if mime and "/" in mime:
        return mime.split("/")[-1].split(";")[0][:8]
    return None


def _clean_report_config(report: dict | None) -> dict | None:
    """Valideer/normaliseer een verslag-config voor auto-generatie na transcriptie.
    Geeft een schone dict terug, of None als er geen (geldig) verslag gevraagd is."""
    if not report or not isinstance(report, dict):
        return None
    kinds = report.get("kinds") or None
    custom = (report.get("custom_prompt") or "").strip() or None
    context = (report.get("context") or "").strip() or None
    if kinds:
        valid = set(prompts.SECTIONS.keys())
        kinds = [k for k in kinds if k in valid]
        if not kinds:
            kinds = None
    if not kinds and not custom:
        return None
    return {"kinds": kinds, "custom_prompt": custom, "context": context}


async def _get_session_or_404(db: AsyncSession, session_id: str, with_reports: bool = False) -> Session:
    stmt = select(Session).where(Session.id == session_id)
    if with_reports:
        stmt = stmt.options(selectinload(Session.reports))
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if obj is None:
        # Zelfde melding voor 'bestaat niet' en 'verlopen' — geen informatielek.
        raise HTTPException(status_code=404, detail="Sessie niet gevonden of verlopen.")
    return obj


# --------------------------------------------------------------------------
# Config & prompts (voor de frontend)
# --------------------------------------------------------------------------
_STT_BACKEND_LABEL = {
    "faster_whisper": "faster-whisper",
    "canary": "NVIDIA Canary",
    "openai": "extern (OpenAI-compatibel)",
}


@router.get("/config")
async def get_config() -> dict:
    s = get_settings()
    backend_label = _STT_BACKEND_LABEL.get(s.stt_backend, s.stt_backend)
    stt_label = f"{backend_label} {s.stt_model}".strip() if s.stt_model else backend_label
    return {
        "max_upload_mb": s.max_upload_mb,
        "retention_workdays": s.retention_workdays,
        "default_language": s.default_language,
        "word_timestamps": s.stt_word_timestamps,
        "audio_optimize_default": s.audio_optimize_default,
        # Model-namen komen uit de env (STT_BACKEND/STT_MODEL/LLM_MODEL) zodat de
        # frontend de werkelijke modellen toont i.p.v. hardcoded teksten.
        "stt_backend": s.stt_backend,
        "stt_model": s.stt_model,
        "stt_label": stt_label,
        "llm_model": s.llm_model,
    }


@router.get("/prompts")
async def get_prompts() -> dict:
    return {"sections": prompts.available_sections()}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Publieke, volledig anonieme statistieken voor het dashboard."""
    return await stats.compute_stats(db)


@router.get("/wait")
async def get_wait(db: AsyncSession = Depends(get_db)) -> dict:
    """Actuele geschatte wachttijd (voor de statuspagina)."""
    return await stats.estimate_wait(db)


# --------------------------------------------------------------------------
# Sessie aanmaken + chunked upload
# --------------------------------------------------------------------------
@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(request: Request, db: AsyncSession = Depends(get_db)) -> CreateSessionResponse:
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    s = get_settings()
    language = (body or {}).get("language") or s.default_language
    optimize = (body or {}).get("optimize")
    if optimize is None:
        optimize = s.audio_optimize_default
    auto_report = _clean_report_config((body or {}).get("report"))

    now = _now()
    obj = Session(
        id=new_token(),
        status=SessionStatus.CREATED,
        language=language,
        optimize_audio=bool(optimize),
        auto_report=auto_report,
        source="record",
        created_at=now,
        updated_at=now,
    )
    db.add(obj)
    await db.commit()
    return CreateSessionResponse(id=obj.id, status=obj.status)


@router.put("/sessions/{session_id}/audio")
async def upload_chunk(session_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Voeg een audio-chunk toe (robuuste chunked upload voor lange opnames)."""
    obj = await _get_session_or_404(db, session_id)
    if obj.status not in (SessionStatus.CREATED,):
        raise HTTPException(status_code=409, detail="Upload is al afgerond.")

    max_bytes = get_settings().max_upload_bytes
    data = await request.body()
    current = storage.raw_audio_path(session_id)
    current_size = current.stat().st_size if current.exists() else 0
    if current_size + len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Maximale bestandsgrootte overschreden.")

    new_size = storage.append_chunk(session_id, data)
    # Onthoud mime/filename van de eerste chunk als meegegeven.
    if obj.audio_mime is None:
        obj.audio_mime = request.headers.get("content-type")
    fname = request.headers.get("x-filename")
    if fname and obj.audio_filename is None:
        obj.audio_filename = fname
    obj.updated_at = _now()
    await db.commit()
    return {"received_bytes": new_size}


@router.post("/sessions/{session_id}/complete")
async def complete_upload(session_id: str, db: AsyncSession = Depends(get_db)) -> SessionStatusOut:
    """Rond de chunked upload af en zet de transcriptie-job op de wachtrij."""
    obj = await _get_session_or_404(db, session_id)
    if obj.status != SessionStatus.CREATED:
        # Idempotent: al afgerond -> gewoon status teruggeven.
        return _status_out(obj)

    raw = storage.raw_audio_path(session_id)
    if not raw.exists() or raw.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="Geen audio ontvangen.")

    obj.audio_path = str(raw)
    obj.audio_bytes = raw.stat().st_size
    obj.audio_format = _audio_format(obj.audio_filename, obj.audio_mime)
    obj.status = SessionStatus.QUEUED
    obj.updated_at = _now()
    await stats.record_event(
        db, "created", source="record", audio_format=obj.audio_format,
        audio_bytes=obj.audio_bytes, language=obj.language,
        report_mode=stats.report_mode(obj.auto_report),
    )
    await db.commit()

    await queue.enqueue_transcription(session_id)
    return _status_out(obj)


# --------------------------------------------------------------------------
# Single-shot upload van een bestaand bestand
# --------------------------------------------------------------------------
@router.post("/upload", response_model=CreateSessionResponse)
async def upload_file(
    file: UploadFile,
    language: str | None = None,
    optimize: bool | None = None,
    report: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> CreateSessionResponse:
    s = get_settings()
    now = _now()
    auto_report = None
    if report:
        try:
            auto_report = _clean_report_config(json.loads(report))
        except (ValueError, TypeError):
            auto_report = None
    obj = Session(
        id=new_token(),
        status=SessionStatus.CREATED,
        language=language or s.default_language,
        optimize_audio=s.audio_optimize_default if optimize is None else bool(optimize),
        auto_report=auto_report,
        source="upload",
        audio_format=_audio_format(file.filename, file.content_type),
        audio_filename=file.filename,
        audio_mime=file.content_type,
        created_at=now,
        updated_at=now,
    )
    db.add(obj)
    await db.commit()

    storage.ensure_session_dir(obj.id)
    written = 0
    with open(storage.raw_audio_path(obj.id), "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > s.max_upload_bytes:
                storage.delete_session_files(obj.id)
                await db.delete(obj)
                await db.commit()
                raise HTTPException(status_code=413, detail="Maximale bestandsgrootte overschreden.")
            out.write(chunk)

    if written == 0:
        raise HTTPException(status_code=400, detail="Leeg bestand.")

    obj.audio_path = str(storage.raw_audio_path(obj.id))
    obj.audio_bytes = written
    obj.status = SessionStatus.QUEUED
    obj.updated_at = _now()
    await stats.record_event(
        db, "created", source="upload", audio_format=obj.audio_format,
        audio_bytes=written, language=obj.language,
        report_mode=stats.report_mode(obj.auto_report),
    )
    await db.commit()

    await queue.enqueue_transcription(obj.id)
    return CreateSessionResponse(id=obj.id, status=obj.status)


# --------------------------------------------------------------------------
# Status & resultaat ophalen
# --------------------------------------------------------------------------
def _status_out(obj: Session) -> SessionStatusOut:
    return SessionStatusOut(
        id=obj.id,
        status=obj.status,
        language=obj.language,
        error=obj.error,
        created_at=obj.created_at,
        processing_finished_at=obj.processing_finished_at,
        expires_at=obj.expires_at,
        has_transcript=bool(obj.transcript),
    )


@router.get("/sessions/{session_id}/status", response_model=SessionStatusOut)
async def get_status(session_id: str, db: AsyncSession = Depends(get_db)) -> SessionStatusOut:
    obj = await _get_session_or_404(db, session_id)
    return _status_out(obj)


@router.get("/sessions/{session_id}", response_model=SessionResultOut)
async def get_result(session_id: str, db: AsyncSession = Depends(get_db)) -> SessionResultOut:
    obj = await _get_session_or_404(db, session_id, with_reports=True)
    segments = None
    if obj.segments:
        segments = [SegmentOut(**seg) for seg in obj.segments]
    return SessionResultOut(
        id=obj.id,
        status=obj.status,
        language=obj.language,
        error=obj.error,
        transcript=obj.transcript,
        segments=segments,
        processing_finished_at=obj.processing_finished_at,
        expires_at=obj.expires_at,
        reports=[_report_out(r) for r in sorted(obj.reports, key=lambda r: r.created_at)],
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    """Verwijder een sessie direct (bestanden + DB-rij). Voor 'weggooien' bij het
    opnemen én als directe privacy-verwijdering door de gebruiker."""
    obj = await _get_session_or_404(db, session_id)
    storage.delete_session_files(session_id)
    await db.delete(obj)
    await db.commit()
    return Response(status_code=204)


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Server-Sent Events: push statusupdates tot een terminale status bereikt is."""
    await _get_session_or_404(db, session_id)  # bestaanscheck

    async def gen():
        last = None
        # Eigen sessie per iteratie zodat we verse data zien.
        from ..db import get_sessionmaker
        maker = get_sessionmaker()
        while True:
            if await request.is_disconnected():
                break
            async with maker() as s:
                res = await s.execute(select(Session).where(Session.id == session_id))
                obj = res.scalar_one_or_none()
            if obj is None:
                yield f"event: gone\ndata: {json.dumps({'id': session_id})}\n\n"
                break
            payload = json.dumps(_status_out(obj).model_dump(mode="json"))
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if obj.status in SessionStatus.TERMINAL:
                break
            await asyncio.sleep(1.5)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------
@router.get("/sessions/{session_id}/audio")
async def download_audio(session_id: str, db: AsyncSession = Depends(get_db)):
    """Download het (originele) geüploade/opgenomen audiobestand."""
    obj = await _get_session_or_404(db, session_id)
    raw = storage.raw_audio_path(session_id)
    if not raw.exists():
        raise HTTPException(status_code=404, detail="Audio niet (meer) beschikbaar.")
    filename = obj.audio_filename or f"audio-{session_id[:8]}"
    await stats.record_event(db, "download", download_kind="audio")
    await db.commit()
    return FileResponse(
        str(raw),
        media_type=obj.audio_mime or "application/octet-stream",
        filename=filename,
    )


@router.get("/sessions/{session_id}/transcript.txt", response_class=PlainTextResponse)
async def download_transcript(session_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    obj = await _get_session_or_404(db, session_id)
    if not obj.transcript:
        raise HTTPException(status_code=404, detail="Nog geen transcript.")
    await stats.record_event(db, "download", download_kind="transcript")
    await db.commit()
    return PlainTextResponse(
        obj.transcript,
        headers={"Content-Disposition": f'attachment; filename="transcript-{session_id[:8]}.txt"'},
    )


# --------------------------------------------------------------------------
# Verslagen (LLM)
# --------------------------------------------------------------------------
def _report_out(r: Report) -> ReportOut:
    return ReportOut(
        id=r.id,
        status=r.status,
        kinds=r.kinds,
        custom_prompt=r.custom_prompt,
        content=r.content,
        error=r.error,
        created_at=r.created_at,
    )


@router.post("/sessions/{session_id}/reports", response_model=ReportOut)
async def create_report(
    session_id: str,
    req: CreateReportRequest,
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    obj = await _get_session_or_404(db, session_id)
    if not obj.transcript:
        raise HTTPException(status_code=409, detail="Transcript nog niet beschikbaar.")
    if not req.kinds and not req.custom_prompt:
        raise HTTPException(status_code=422, detail="Geef 'kinds' of 'custom_prompt' op.")

    valid = set(prompts.SECTIONS.keys())
    if req.kinds and not set(req.kinds).issubset(valid):
        raise HTTPException(status_code=422, detail="Onbekende sectie(s) opgegeven.")

    now = _now()
    report = Report(
        id=new_token(),
        session_id=session_id,
        kinds=req.kinds,
        custom_prompt=req.custom_prompt,
        context=req.context,
        status=ReportStatus.QUEUED,
        created_at=now,
        updated_at=now,
    )
    db.add(report)
    await db.commit()

    await queue.enqueue_report(report.id)
    return _report_out(report)


@router.post("/sessions/{session_id}/feedback")
async def submit_feedback(
    session_id: str, req: FeedbackRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Anonieme tevredenheidsscore (1–5 sterren). Slaat alleen de score op, geen inhoud."""
    await _get_session_or_404(db, session_id)  # sessie moet bestaan
    if not (1 <= req.stars <= 5):
        raise HTTPException(status_code=422, detail="stars moet 1..5 zijn.")
    target = req.target if req.target in ("transcript", "verslag") else "resultaat"
    await stats.record_event(db, "feedback", stars=req.stars, target=target)
    await db.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}/reports/{report_id}", response_model=ReportOut)
async def get_report(session_id: str, report_id: str, db: AsyncSession = Depends(get_db)) -> ReportOut:
    res = await db.execute(
        select(Report).where(Report.id == report_id, Report.session_id == session_id)
    )
    r = res.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Verslag niet gevonden.")
    return _report_out(r)


@router.patch("/sessions/{session_id}/reports/{report_id}", response_model=ReportOut)
async def update_report(
    session_id: str, report_id: str, req: UpdateReportRequest, db: AsyncSession = Depends(get_db)
) -> ReportOut:
    """Bewerk de tekst van een afgerond verslag (handmatige correctie in de app)."""
    res = await db.execute(
        select(Report).where(Report.id == report_id, Report.session_id == session_id)
    )
    r = res.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Verslag niet gevonden.")
    if r.status != ReportStatus.DONE:
        raise HTTPException(status_code=409, detail="Alleen een afgerond verslag kan bewerkt worden.")
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="Lege inhoud.")
    r.content = content
    r.updated_at = _now()
    await db.commit()
    await db.refresh(r)
    return _report_out(r)


@router.delete("/sessions/{session_id}/reports/{report_id}", status_code=204)
async def delete_report(
    session_id: str, report_id: str, db: AsyncSession = Depends(get_db)
) -> Response:
    """Verwijder één verslag (bijv. een eerdere, overbodige generatie). Idempotent:
    een reeds verwijderd verslag geeft ook 204."""
    res = await db.execute(
        select(Report).where(Report.id == report_id, Report.session_id == session_id)
    )
    r = res.scalar_one_or_none()
    if r is not None:
        await db.delete(r)
        await db.commit()
    return Response(status_code=204)


async def _get_report_content_or_404(db: AsyncSession, session_id: str, report_id: str) -> Report:
    res = await db.execute(
        select(Report).where(Report.id == report_id, Report.session_id == session_id)
    )
    r = res.scalar_one_or_none()
    if r is None or not r.content:
        raise HTTPException(status_code=404, detail="Verslag niet gevonden.")
    return r


# Downloads onder een extra pad-segment zodat ze niet door de generieke
# /reports/{report_id}-route worden opgeslokt (die ving eerder "{id}.md" op).
@router.get("/sessions/{session_id}/reports/{report_id}/download.md", response_class=PlainTextResponse)
async def download_report_md(session_id: str, report_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    r = await _get_report_content_or_404(db, session_id, report_id)
    await stats.record_event(db, "download", download_kind="report_md")
    await db.commit()
    return PlainTextResponse(
        r.content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="verslag-{report_id[:8]}.md"'},
    )


@router.get("/sessions/{session_id}/reports/{report_id}/download.docx")
async def download_report_docx(session_id: str, report_id: str, db: AsyncSession = Depends(get_db)):
    """Zet het Markdown-verslag om naar een Word-document via pandoc."""
    r = await _get_report_content_or_404(db, session_id, report_id)
    fd, out_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)

    def _convert() -> subprocess.CompletedProcess:
        return subprocess.run(
            ["pandoc", "-f", "markdown+hard_line_breaks", "-t", "docx", "-o", out_path],
            input=r.content, text=True, capture_output=True,
        )

    proc = await asyncio.to_thread(_convert)
    if proc.returncode != 0:
        os.remove(out_path)
        raise HTTPException(status_code=500, detail="Word-conversie mislukt (pandoc).")
    await stats.record_event(db, "download", download_kind="report_docx")
    await db.commit()
    return FileResponse(
        out_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"verslag-{report_id[:8]}.docx",
        background=BackgroundTask(os.remove, out_path),  # temp opruimen na verzenden
    )
