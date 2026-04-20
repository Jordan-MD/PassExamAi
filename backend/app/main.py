import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.api.v1 import documents, roadmap, chapters, exam, progress, projects, sources

logger = logging.getLogger(__name__)


# ── Lifespan : startup / shutdown propres ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère le cycle de vie de l'application.
    Startup  : initialise les ressources partagées (httpx client, etc.)
    Shutdown : ferme proprement les connexions ouvertes.
    """
    logger.info("PassExamAI démarrage...")
    yield
    # Shutdown : ferme le client httpx Jina (singleton dans embeddings.py)
    from app.rag.embeddings import _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        logger.info("httpx client Jina fermé proprement.")
    logger.info("PassExamAI arrêté.")


app = FastAPI(
    title="PassExamAI Backend",
    description="AI-powered exam preparation platform — GCD4F 2026",
    version="3.2.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
_allowed_origins = [
    settings.frontend_url,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Pydantic validation errors → 422 avec détails lisibles.
    Sans ce handler, FastAPI retourne déjà 422 mais le format peut varier.
    """
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body) if hasattr(exc, 'body') else None},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Fallback pour les exceptions non catchées.
    NE CATCH PAS HTTPException — FastAPI les gère en amont avec les bons status codes.
    """
    # ✅ Laisse FastAPI gérer HTTPException normalement
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)

    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."},
    )


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(projects.router,  prefix="/api/v1/projects",  tags=["Projects"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(roadmap.router,   prefix="/api/v1/roadmap",   tags=["Roadmap"])
app.include_router(chapters.router,  prefix="/api/v1/chapters",  tags=["Chapters"])
app.include_router(exam.router,      prefix="/api/v1/exam",      tags=["Exam"])
app.include_router(progress.router,  prefix="/api/v1/progress",  tags=["Progress"])
app.include_router(sources.router,   prefix="/api/v1/sources",   tags=["Sources"])


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "PassExamAI Backend", "version": "3.1.0"}