import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.errors import ok, register_error_handlers
from app.routes import calls, patients, vapi
from app.seed import seed_if_empty

settings = get_settings()
logging.basicConfig(
    stream=sys.stdout,
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all is idempotent: creates missing tables, never alters existing
    # ones. Fine for a take-home; a real service would use Alembic migrations.
    Base.metadata.create_all(engine)
    if settings.seed_data:
        with SessionLocal() as db:
            seed_if_empty(db)
    log.info("Startup complete")
    yield


app = FastAPI(
    title="Voice Patient Intake API",
    description="Patient registration backend for a Vapi voice agent.",
    version="1.0.0",
    lifespan=lifespan,
)
register_error_handlers(app)
app.include_router(patients.router)
app.include_router(calls.router)
app.include_router(vapi.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/ping", tags=["meta"])
def ping():
    """Liveness check without touching the DB, for an uptime pinger that keeps
    the free Render instance awake without waking the database."""
    return ok({"status": "ok"})


@app.get("/health", tags=["meta"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return ok({"status": "ok"})
