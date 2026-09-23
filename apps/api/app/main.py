"""ShopperMind AI — API entrypoint.

An always-on shopper intelligence platform. The five questions every module serves:
who is buying, what are they buying, why are they buying, what is stopping them, and what
should we offer them next.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.db import Base, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("shoppermind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401  — registers every table on the metadata

    Base.metadata.create_all(bind=engine)
    log.info(
        "ShopperMind API up · env=%s · azure_openai=%s speech=%s vision=%s language=%s",
        settings.shoppermind_env, settings.openai_enabled, settings.speech_enabled,
        settings.vision_enabled, settings.language_enabled,
    )
    if not settings.openai_enabled:
        log.info(
            "Azure OpenAI is not configured — the copilot will use the local reasoner. "
            "Answers stay grounded in real module output; only the phrasing is simpler."
        )
    yield
    log.info("ShopperMind API shutting down")


app = FastAPI(
    title="ShopperMind AI",
    description=(
        "AI shopper intelligence for QSR and retail. Turns customer data into business "
        "decisions: what happened, why it happened, what to do, and whether it worked."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    import time

    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Response-Time-Ms"] = f"{(time.monotonic() - started) * 1000:.0f}"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Return a 500 the browser can actually read.

    Starlette's server-error handling sits outside CORSMiddleware, so a 500 would
    otherwise reach the browser with no Access-Control-Allow-Origin header. The browser
    then reports a CORS failure and the real error never surfaces in the client — which
    sends whoever is debugging it in entirely the wrong direction.
    """
    log.exception("Unhandled error on %s %s", request.method, request.url.path)

    headers: dict[str, str] = {}
    origin = request.headers.get("origin")
    if origin and (origin in settings.cors_origin_list or "*" in settings.cors_origin_list):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"

    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. The error has been logged."},
        headers=headers,
    )


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "shoppermind-api", "version": app.version}


@app.get("/ready", tags=["meta"])
def ready():
    """Readiness for Azure Container Apps: the database has to actually answer."""
    from sqlalchemy import text

    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        return JSONResponse(
            status_code=503, content={"status": "not-ready", "database": str(exc)[:200]}
        )
    finally:
        db.close()


@app.get("/", tags=["meta"])
def root():
    return {
        "product": "ShopperMind AI",
        "tagline": "Understand. Predict. Personalise. Act.",
        "docs": "/docs",
        "stack": ["Listen", "Understand", "Predict", "Recommend", "Act", "Learn"],
    }


# ── routes ──────────────────────────────────────────────────────────────────
from app.api.v1.routers import (  # noqa: E402
    auth,
    cameras,
    copilot,
    ingest,
    intelligence,
    simulator,
    voice,
    workspace,
)

API_PREFIX = "/api/v1"
for module in (auth, intelligence, copilot, voice, simulator, cameras, ingest, workspace):
    app.include_router(module.router, prefix=API_PREFIX)
