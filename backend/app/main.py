"""FastAPI-applicatie: alleen de API. De frontend wordt door de `web`-service
(Caddy) geserveerd en proxyt /api hierheen.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import init_db
from .queue import close_pool

# Minimale, privacy-vriendelijke logging (nooit transcript-inhoud).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("transcribe.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("API gestart (backend=%s, model=%s)", get_settings().stt_backend, get_settings().stt_model)
    yield
    await close_pool()


# Swagger/OpenAPI alleen aanzetten als expliciet gevraagd (kleiner aanvalsoppervlak).
_docs_on = get_settings().expose_api_docs
app = FastAPI(
    title="Anonieme transcriptie",
    lifespan=lifespan,
    docs_url="/api/docs" if _docs_on else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _docs_on else None,
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


from .api.routes import router as api_router  # noqa: E402

app.include_router(api_router)

# Optioneel: laat de API zelf de statische frontend serveren (handig voor lokale
# dev / single-container). In de standaard compose-opzet doet Caddy dit. Zet
# SERVE_FRONTEND=/pad/naar/frontend om aan te zetten. De /api-routes hierboven
# hebben voorrang; de mount vangt de rest (index.html, /js, /css).
import os  # noqa: E402

_frontend_dir = os.environ.get("SERVE_FRONTEND")
if _frontend_dir and os.path.isdir(_frontend_dir):
    from fastapi.staticfiles import StaticFiles  # noqa: E402

    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
    log.info("Frontend geserveerd vanuit %s", _frontend_dir)
