"""FastAPI application.

Run (from backend/):  uv run python -m uvicorn app.main:app --reload --port 8000
API docs: http://localhost:8000/docs
"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.connectors import scheduler as connector_scheduler
from app.core.config import FRONTEND_DIST, settings
from app.db.session import init_db
from app.services.analytics import warm_cache
from app.services.errors import NotFoundError
from app.twin.engine import start_engine, stop_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("utilities_agent")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    dropped = init_db()
    if dropped:
        log.info("Dropped legacy demo tables: %s", ", ".join(dropped))
    threading.Thread(target=warm_cache, name="warm-cache", daemon=True).start()   # load rows in the background
    if settings.twin_autostart:
        start_engine()          # live telemetry (SIMULATED until a real gateway posts to /api/twin/ingest)
    connector_scheduler.start()    # pulls from connected systems on their schedule
    yield
    connector_scheduler.stop()
    stop_engine()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(NotFoundError)
    async def _not_found(_req: Request, exc: NotFoundError):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def _bad_request(_req: Request, exc: ValueError):
        # Services raise ValueError for invalid user input (unknown utility, tag, alert transition...).
        return JSONResponse({"detail": str(exc)}, status_code=400)

    app.include_router(api_router)

    # Serve the built React app (frontend/dist) from the same origin in production.
    if settings.serve_frontend and FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()
