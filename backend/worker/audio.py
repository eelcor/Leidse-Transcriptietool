"""Audio-voorbewerking in de worker.

Canary (en faster-whisper) willen 16kHz mono. We transcoderen elk aangeleverd
formaat (webm/opus, mp3, m4a, ogg, wav, flac) met ffmpeg naar 16kHz mono wav.

BELANGRIJK (zie BOUWPROMPT): pas hier GEEN agressieve spectrale denoising toe.
Zwaar denoisen introduceert artefacten die de WER van Canary verslechteren.
De veilige keten is: browser-AGC + lichte noiseSuppression + hoogdoorlaat aan
de opnamekant; server-side alleen resamplen naar 16kHz mono.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


# ASR-veilige optimalisatie-keten (geen agressieve denoising):
#   highpass ~80Hz  -> weg met laagfrequente brom/rommel
#   loudnorm        -> EBU R128 loudness-normalisatie naar een spraak-target,
#                      zodat te zachte/harde opnames een consistent niveau krijgen
# Dit verbetert de ASR-robuustheid zonder de stem te beschadigen.
_ASR_FILTER = "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11"


def resample_to_wav(src: str | Path, dst: str | Path, optimize: bool = True) -> Path:
    """Transcodeer naar 16kHz mono wav. Met optimize=True: ASR-veilige
    voorbewerking (hoogdoorlaat + loudness-normalisatie)."""
    src, dst = Path(src), Path(dst)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(src),
        "-ac", "1",        # mono
        "-ar", "16000",    # 16 kHz
    ]
    if optimize:
        cmd += ["-af", _ASR_FILTER]
    cmd += ["-c:a", "pcm_s16le", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg transcodering mislukt: {proc.stderr.strip()[:500]}")
    return dst
