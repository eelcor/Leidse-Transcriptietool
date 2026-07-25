"""Tests voor de externe OpenAI-STT-backend (parsing + fallback), met gemockte HTTP."""
import httpx

from worker.stt.openai_backend import OpenAISTTBackend, _parse


class FakeResp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_parse_verbose_json():
    body = {"text": "Hallo wereld.", "segments": [
        {"start": 0.0, "end": 1.2, "text": " Hallo"},
        {"start": 1.2, "end": 2.0, "text": " wereld."},
    ]}
    r = _parse(body)
    assert r.text == "Hallo wereld."
    assert len(r.segments) == 2
    assert r.segments[0].start == 0.0 and r.segments[0].text == "Hallo"


def test_transcribe_verbose_json(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"; wav.write_bytes(b"RIFFfake")
    b = OpenAISTTBackend(base_url="http://stt/v1", model="whisper-1")

    calls = []

    def fake_post(url, data=None, files=None, headers=None, timeout=None):
        calls.append(data)
        return FakeResp(200, {"text": "Test.", "segments": [{"start": 0, "end": 1, "text": "Test."}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    res = b.transcribe(str(wav), "nl", word_timestamps=True)
    assert res.text == "Test."
    assert len(res.segments) == 1
    # eerste poging vraagt verbose_json met segment-timestamps
    assert calls[0]["response_format"] == "verbose_json"
    assert calls[0]["model"] == "whisper-1" and calls[0]["language"] == "nl"


def test_transcribe_falls_back_to_json(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"; wav.write_bytes(b"RIFFfake")
    b = OpenAISTTBackend(base_url="http://stt/v1", model="whisper-1")

    seq = [FakeResp(400), FakeResp(200, {"text": "Alleen tekst."})]

    def fake_post(url, data=None, files=None, headers=None, timeout=None):
        return seq.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    res = b.transcribe(str(wav), "nl", word_timestamps=True)
    assert res.text == "Alleen tekst."
    assert res.segments == []  # geen segmenten in het eenvoudige formaat
