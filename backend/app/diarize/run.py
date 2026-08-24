"""Diarisatie-orchestratie: draai de backend en sla het resultaat op in de diarizations-rij.

Losgekoppeld van arq/Redis zodat het zonder queue/GPU te testen is (de worker is een dunne
wrapper hieromheen). Faalt ZACHT: een fout in de diarizer laat de job niet klappen — de rij
krijgt status=failed en het transcript blijft gewoon bruikbaar (diarisatie is verrijking).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from .. import storage
from ..config import get_settings
from ..models import Diarization, DiarizationStatus, Session
from .base import DiarizeBackend
from .merge import merge as merge_segments
from .merge import pick_speaker_clips

log = logging.getLogger("transcribe.diarize.run")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _flatten_words(segments: list[dict] | None) -> list[dict]:
    """Plat de woord-timestamps uit de STT-segments (sessions.segments) tot één lijst."""
    words: list[dict] = []
    for seg in segments or []:
        words.extend(seg.get("words") or [])
    return words


async def run_diarization(maker: async_sessionmaker, session_id: str, diar_id: str, backend: DiarizeBackend) -> str:
    """Voer de diarisatie uit voor `diar_id` en werk de rij bij. Retour: 'ok' | 'failed' | 'gone'.

    Werpt zelf niets naar boven (soft-fail); de aanroeper hoeft geen fout af te vangen.
    De merge (fase 3) verrijkt hierna `payload` met gelabelde segments.
    """
    async with maker() as db:
        diar = await db.get(Diarization, diar_id)
        sess = await db.get(Session, session_id)
        if diar is None or sess is None:
            return "gone"
        min_spk, max_spk = diar.min_speakers, diar.max_speakers
        sess_segments = sess.segments
        diar.status = DiarizationStatus.RUNNING
        diar.updated_at = _now()
        await db.commit()

    try:
        wav = str(storage.wav_path(session_id))
        loop = asyncio.get_running_loop()
        turns = await loop.run_in_executor(None, lambda: backend.diarize(wav, min_spk, max_spk))
    except Exception as exc:  # soft-fail: nooit de job laten klappen
        log.exception("Diarisatie mislukt voor sessie %s", session_id[:8])
        async with maker() as db:
            diar = await db.get(Diarization, diar_id)
            if diar is not None:
                diar.status = DiarizationStatus.FAILED
                diar.error = f"Diarisatie mislukt: {type(exc).__name__}"
                diar.updated_at = _now()
                await db.commit()
        return "failed"

    # Aantal GEVONDEN sprekers = rauwe pyannote-labels (onafhankelijk van de merge).
    num_speakers = len({t.speaker for t in turns})
    # Merge de STT-woorden met de spreker-turns tot hersneden, gelabelde segments.
    s = get_settings()
    words = _flatten_words(sess_segments)
    merged = merge_segments(
        words, [t.as_dict() for t in turns],
        min_gap=s.diarize_min_gap, min_segment=s.diarize_min_segment,
    )
    payload = {
        "backend": backend.name,
        "num_speakers": num_speakers,
        "turns": [t.as_dict() for t in turns],
        "segments": merged["segments"],
        "speaker_map": merged["speaker_map"],
        # Per spreker een goed hoorbaar fragment (langste aaneengesloten spraak) voor de UI.
        "clips": pick_speaker_clips(merged["segments"]),
    }
    async with maker() as db:
        diar = await db.get(Diarization, diar_id)
        if diar is None:
            return "gone"
        diar.status = DiarizationStatus.DONE
        diar.num_speakers = num_speakers
        diar.payload = payload
        diar.updated_at = _now()
        await db.commit()
    log.info("Diarisatie klaar voor sessie %s: %d spreker(s).", session_id[:8], num_speakers)
    return "ok"
