# app/main.py — CFIS v3 + Legacy Emthethal AI
# Mounts CFIS router at /api/cfis/v1/* alongside existing legacy routes.
# Legacy routes preserved to avoid breaking the running system.

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from .models.orm import Base
from .database import engine
import asyncio
import os
import logging

limiter = Limiter(key_func=get_remote_address)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Emthethal AI — CFIS v3 + Healthcare Compliance Engine",
    description=(
        "Sovereign AI-Powered Document Intelligence & Healthcare Compliance System. "
        "CFIS Phase 1: Hybrid PDF extraction | Arabic-first | Zero hardcoded geometry."
    ),
    version="3.0.0",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    logger.info("Emthethal AI + CFIS v3 starting up...")

    # Legacy: SQLAlchemy table init
    logger.info("Initializing legacy database tables...")
    try:
        async with engine.begin() as conn:

            await conn.run_sync(Base.metadata.create_all)
        logger.info("Legacy database tables ready.")
    except Exception as e:
        logger.warning(f"Legacy DB init warning (non-fatal): {e}")

    # CFIS: asyncpg table init
    logger.info("Initializing CFIS database tables...")
    try:
        import app.db as cfis_db
        await cfis_db.init_db()
        logger.info("CFIS database tables ready.")
    except Exception as e:
        logger.warning(f"CFIS DB init warning (non-fatal if no DATABASE_URL): {e}")

@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()
    logger.info("Emthethal AI shut down.")

# ── Health endpoints ────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Emthethal AI + CFIS v3", "status": "operational"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0",
        "schema": "v2",
        "pipeline": "v3",
        "extraction": "hybrid",
    }


# ── CFIS v3 routes ──────────────────────────────────────────────────────────
from .api.router import router as cfis_router
app.include_router(cfis_router)

# ── Phase 2B geometry debug routes ─────────────────────────────────────────
from .api.routes.geometry_debug import router as geometry_debug_router
app.include_router(geometry_debug_router)

# ── Phase 3 Deterministic Pipeline API ─────────────────────────────────────
from .api.routes.pipeline import router as pipeline_router
from .api.routes.hitl import router as hitl_router
app.include_router(pipeline_router)
app.include_router(hitl_router)

# ── Serve Frontend (dist/) ──────────────────────────────────────────────────
# The built Vite frontend is served as static files.
# All non-API routes fall back to index.html (SPA routing).
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
_FRONTEND_DIST = os.path.abspath(_FRONTEND_DIST)

if os.path.isdir(_FRONTEND_DIST):
    # Serve /assets/* statically
    app.mount("/assets", StaticFiles(directory=os.path.join(_FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str, request: Request):
        """SPA fallback: any unknown route returns index.html."""
        # Don't intercept API routes
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        index = os.path.join(_FRONTEND_DIST, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        return JSONResponse({"detail": "Frontend not built"}, status_code=503)
else:
    logger.warning(f"Frontend dist not found at {_FRONTEND_DIST} — UI will not be served")

