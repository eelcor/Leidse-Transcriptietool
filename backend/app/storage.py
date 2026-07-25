"""Bestandsopslag per sessie op een lokaal volume.

Layout:  {STORAGE_DIR}/sessions/{session_id}/
    raw            -> zoals geüpload (webm/mp3/...); append-baar voor chunked upload
    audio.wav      -> 16kHz mono wav (door de worker gegenereerd)

De hele map wordt bij het opschonen hard verwijderd.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .config import get_settings


def _base() -> Path:
    return Path(get_settings().storage_dir) / "sessions"


def session_dir(session_id: str) -> Path:
    d = _base() / session_id
    return d


def ensure_session_dir(session_id: str) -> Path:
    d = session_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def raw_audio_path(session_id: str) -> Path:
    return session_dir(session_id) / "raw"


def wav_path(session_id: str) -> Path:
    return session_dir(session_id) / "audio.wav"


def append_chunk(session_id: str, data: bytes) -> int:
    """Voeg bytes toe aan het ruwe audiobestand (chunked upload). Geeft nieuwe grootte terug."""
    ensure_session_dir(session_id)
    path = raw_audio_path(session_id)
    with open(path, "ab") as f:
        f.write(data)
    return path.stat().st_size


def delete_session_files(session_id: str) -> None:
    d = session_dir(session_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
