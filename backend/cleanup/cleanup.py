"""Geplande opschoontaak: verwijdert verlopen sessies hard (bestanden + DB-rijen).

Een sessie verloopt `expires_at` — dat is werkdag-bewust gezet zodra de
verwerking klaar was (2 werkdagen ná afronden). Sessies waarvan de verwerking
nog niet klaar is hebben `expires_at IS NULL` en worden hier niet aangeraakt.

Draait als aparte container in een lus (CLEANUP_INTERVAL_SECONDS).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker, init_db
from app.models import Session
from app import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("transcribe.cleanup")


async def purge_expired() -> int:
    maker = get_sessionmaker()
    now = datetime.now(timezone.utc)
    removed = 0
    async with maker() as db:
        res = await db.execute(
            select(Session).where(Session.expires_at.is_not(None), Session.expires_at <= now)
        )
        expired = res.scalars().all()
        for obj in expired:
            # Eerst bestanden (audio + wav), dan de DB-rij (reports cascade).
            storage.delete_session_files(obj.id)
            await db.delete(obj)
            removed += 1
        if removed:
            await db.commit()
    if removed:
        log.info("Opgeschoond: %d verlopen sessie(s) verwijderd.", removed)
    return removed


async def main() -> None:
    await init_db()
    interval = get_settings().cleanup_interval_seconds
    log.info("Cleanup-scheduler gestart (interval=%ss).", interval)
    while True:
        try:
            await purge_expired()
        except Exception:
            log.exception("Opschonen mislukt; probeer opnieuw bij de volgende ronde.")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
