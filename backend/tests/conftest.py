"""Test-fixtures: SQLite in plaats van Postgres, en een nep-queue (geen Redis).

Env-vars worden gezet vóór de app geïmporteerd wordt, zodat get_settings() ze
oppikt. De queue-functies worden vervangen door async no-ops zodat er geen
Redis nodig is voor de API-tests.
"""
import os
import tempfile

import pytest
import pytest_asyncio

# --- Env instellen vóór app-import ---
_tmp = tempfile.mkdtemp(prefix="transcribe-test-")
# File-based SQLite (niet :memory:) zodat alle pool-connecties dezelfde DB delen.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["STORAGE_DIR"] = _tmp
os.environ.setdefault("PROMPTS_FILE", os.path.join(os.path.dirname(__file__), "..", "..", "PROMPTS.md"))


@pytest_asyncio.fixture
async def client(monkeypatch):
    import httpx

    from app import queue
    from app.db import init_db
    from app.main import app

    # Nep-queue: registreer welke jobs zouden zijn ge-enqueued.
    enqueued = {"stt": [], "report": [], "diarize": []}

    async def fake_stt(session_id):
        enqueued["stt"].append(session_id)

    async def fake_report(report_id):
        enqueued["report"].append(report_id)

    async def fake_diarize(session_id, diar_id):
        enqueued["diarize"].append((session_id, diar_id))

    monkeypatch.setattr(queue, "enqueue_transcription", fake_stt)
    monkeypatch.setattr(queue, "enqueue_report", fake_report)
    monkeypatch.setattr(queue, "enqueue_diarization", fake_diarize)

    await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        c.enqueued = enqueued  # type: ignore[attr-defined]
        yield c
