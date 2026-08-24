"""Fase 1: het uploadpad moet niet-audio (Word/PDF/tekst) duidelijk afwijzen
i.p.v. laat en generiek te falen. We testen de NoAudioError-poort in audio.py."""
import subprocess

import pytest

from worker import audio


def test_resample_raises_no_audio_error_when_no_stream(monkeypatch, tmp_path):
    # Doe alsof ffprobe geen audiospoor vindt (bv. een geüpload Word-bestand).
    monkeypatch.setattr(audio, "probe_has_audio", lambda src: False)
    src = tmp_path / "aantekeningen.docx"
    src.write_bytes(b"PK\x03\x04 dit is geen audio")
    with pytest.raises(audio.NoAudioError):
        audio.resample_to_wav(str(src), str(tmp_path / "out.wav"))


def test_probe_has_audio_true_when_ffprobe_missing(monkeypatch, tmp_path):
    # Zonder ffprobe geen valse afwijzing: laat ffmpeg alsnog beslissen.
    def _boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(audio.subprocess, "run", _boom)
    assert audio.probe_has_audio(str(tmp_path / "x.wav")) is True


def test_probe_has_audio_reads_ffprobe_output(monkeypatch, tmp_path):
    class _R:
        returncode = 0
        stdout = "audio\n"
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: _R())
    assert audio.probe_has_audio(str(tmp_path / "x.wav")) is True

    class _R2:
        returncode = 0
        stdout = ""  # geen audiostream
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: _R2())
    assert audio.probe_has_audio(str(tmp_path / "x.docx")) is False
