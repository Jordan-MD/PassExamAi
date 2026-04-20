import logging
import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.schemas.documents import DocumentChunk

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "jina-embeddings-v3"
EMBEDDING_DIMENSIONS = 768       # Matryoshka — zéro migration SQL
EMBEDDING_BATCH_SIZE = 50        # Limite API Jina
JINA_URL = "https://api.jina.ai/v1/embeddings"

# ── Client HTTP réutilisé entre les appels (évite TCP/TLS par batch) ───────
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Singleton httpx — créé une seule fois, réutilisé partout."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
    return _http_client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def _embed_batch(texts: list[str], task: str) -> list[list[float]]:
    """
    Appelle l'API Jina pour un batch de textes.
    task : "retrieval.passage" (stockage) ou "retrieval.query" (recherche)
    """
    client = _get_http_client()
    response = await client.post(
        JINA_URL,
        headers={
            "Authorization": f"Bearer {settings.jina_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": EMBEDDING_MODEL,
            "input": texts,
            "dimensions": EMBEDDING_DIMENSIONS,
            "task": task,
        },
    )
    response.raise_for_status()
    data = response.json()
    # Trie par index pour garantir l'ordre (l'API peut renvoyer dans n'importe quel ordre)
    items = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in items]


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Embeddings de STOCKAGE — task: retrieval.passage.
    À utiliser lors de l'ingestion de documents et de liens.
    """
    if not texts:
        return []

    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i: i + EMBEDDING_BATCH_SIZE]
        logger.info(
            "Embedding batch %d/%d (%d textes) — task=retrieval.passage",
            i // EMBEDDING_BATCH_SIZE + 1,
            (len(texts) + EMBEDDING_BATCH_SIZE - 1) // EMBEDDING_BATCH_SIZE,
            len(batch),
        )
        embeddings = await _embed_batch(batch, task="retrieval.passage")
        all_embeddings.extend(embeddings)

    logger.info("✅ %d embeddings générés (dim=%d, Jina v3)", len(all_embeddings), EMBEDDING_DIMENSIONS)
    return all_embeddings


async def get_query_embedding(query: str) -> list[float]:
    """
    Embedding de REQUÊTE — task: retrieval.query.
    À utiliser uniquement dans retrieval.py pour la recherche sémantique.

    CRITIQUE : utiliser un task différent du stockage est ce qui donne
    l'avantage asymétrique de Jina v3 (+5-15% recall vs task identique).
    """
    result = await _embed_batch([query], task="retrieval.query")
    return result[0]


async def embed_chunks(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Génère les embeddings de stockage pour une liste de chunks."""
    if not chunks:
        return []
    texts = [chunk.content for chunk in chunks]
    embeddings = await get_embeddings(texts)
    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding
    return chunks