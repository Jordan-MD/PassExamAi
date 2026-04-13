from app.ai.llm_client import get_embeddings
from app.schemas.documents import DocumentChunk
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Batch size pour éviter les limites de l'API OpenAI
EMBEDDING_BATCH_SIZE = 100


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def embed_chunks(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """
    Génère les embeddings pour tous les chunks en batches.
    Retourne les chunks avec le champ embedding renseigné.
    """
    if not chunks:
        return []

    embedded_chunks = []

    # Traitement par batch pour respecter les limites API
    for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[i : i + EMBEDDING_BATCH_SIZE]
        texts = [chunk.content for chunk in batch]

        logger.info(
            f"Embedding batch {i // EMBEDDING_BATCH_SIZE + 1} "
            f"({len(texts)} chunks)..."
        )

        embeddings = await get_embeddings(texts)

        for chunk, embedding in zip(batch, embeddings):
            chunk.embedding = embedding
            embedded_chunks.append(chunk)

    logger.info(f"✅ {len(embedded_chunks)} chunks embarqués avec succès")
    return embedded_chunks