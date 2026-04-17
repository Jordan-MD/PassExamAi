import logging
import asyncio
import json
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings
from app.schemas.documents import DocumentChunk

logger = logging.getLogger(__name__)

# ── Init client (nouveau SDK) ────────────────────────────────
from google import genai
from google.genai import types as genai_types

_client = genai.Client(api_key=settings.gemini_api_key)

EMBEDDING_BATCH_SIZE = 50         # Limite safe Gemini API
EMBEDDING_MODEL = "gemini-embedding-001"   # Supported by embedContent on current API

def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # region agent log
    try:
        with open("/home/bedane/dev/Projects AI/passexamai/.cursor/debug-a1f71d.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "a1f71d",
                "runId": "run1",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # endregion


# ── Core batch embed ────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def _embed_batch(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """
    Appelle l'API Gemini Embeddings pour un batch.
    Exécuté dans un thread (SDK sync) pour ne pas bloquer l'event loop.
    """
    def _sync():
        _debug_log("H4", "embeddings.py:53", "embed_batch_sync_start", {
            "batch_size": len(texts),
            "task_type": task_type,
            "model": EMBEDDING_MODEL,
        })
        result = _client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=texts,
            config=genai_types.EmbedContentConfig(task_type=task_type),
        )
        # result.embeddings est une liste d'objets ContentEmbedding
        return [e.values for e in result.embeddings]

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _sync)
    except Exception as exc:
        _debug_log("H4", "embeddings.py:67", "embed_batch_exception", {
            "exc_type": type(exc).__name__,
            "exc": str(exc)[:300],
            "batch_size": len(texts),
        })
        raise


# ── Public API ──────────────────────────────────────────────

async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Génère des embeddings Gemini pour une liste de textes (stockage RAG).
    Retourne une liste de vecteurs 768 dimensions.
    """
    if not texts:
        return []

    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        logger.info(
            "Embedding batch %d (%d textes) via Gemini...",
            i // EMBEDDING_BATCH_SIZE + 1,
            len(batch),
        )
        embeddings = await _embed_batch(batch, task_type="RETRIEVAL_DOCUMENT")
        all_embeddings.extend(embeddings)

    logger.info("✅ %d embeddings générés (dim=768)", len(all_embeddings))
    return all_embeddings


async def get_query_embedding(query: str) -> list[float]:
    """
    Embedding pour une requête de recherche.
    task_type RETRIEVAL_QUERY améliore la précision vs RETRIEVAL_DOCUMENT.
    """
    result = await _embed_batch([query], task_type="RETRIEVAL_QUERY")
    return result[0]


async def embed_chunks(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Génère les embeddings pour tous les chunks et les attache."""
    if not chunks:
        return []

    texts = [chunk.content for chunk in chunks]
    embeddings = await get_embeddings(texts)

    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding

    return chunks