import logging
from app.db.supabase_client import supabase
from app.rag.embeddings import get_query_embedding
from app.core.config import settings

logger = logging.getLogger(__name__)


async def retrieve_chunks(
    query: str,
    project_id: str,
    chapter_hint: str | None = None,
    top_k: int | None = None,
    min_similarity: float | None = None,
) -> list[dict]:

    k = top_k or settings.top_k_retrieval
    threshold = min_similarity

    # ✅ task="retrieval.query" — différent du stockage → précision asymétrique Jina v3
    query_vector = await get_query_embedding(query)

    # Seul filtre fiable : project_id (isolement des données par utilisateur)
    metadata_filter: dict = {"project_id": project_id}

    try:
        response = supabase.rpc(
            "match_document_chunks",
            {
                "query_embedding": query_vector,
                "match_count": k,
                "filter": metadata_filter,
            },
        ).execute()

        chunks: list[dict] = response.data or []

        if threshold is not None:
            chunks = [c for c in chunks if c.get("similarity", 0) >= threshold]

        logger.info(
            "Retrieval '%s' → %d chunks (project=%s, seuil=%s)",
            query[:50], len(chunks), project_id[:8], threshold,
        )
        return chunks

    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        return []


def assess_rag_quality(chunks: list[dict]) -> tuple[bool, float]:
    """
    Évalue si les chunks RAG sont suffisants pour répondre sans web search.
    Retourne (is_sufficient, avg_similarity).
    """
    if not chunks:
        return False, 0.0

    similarities = [c.get("similarity", 0.0) for c in chunks]
    avg_sim = sum(similarities) / len(similarities)
    top_sim = max(similarities)

    is_sufficient = (
        len(chunks) >= settings.rag_min_chunks_threshold
        and top_sim >= settings.rag_similarity_threshold
    )

    logger.info(
        "RAG quality: %d chunks | avg=%.3f | top=%.3f → %s",
        len(chunks), avg_sim, top_sim,
        "✅ sufficient" if is_sufficient else "⚠️ insufficient → web fallback",
    )
    return is_sufficient, avg_sim


async def retrieve_for_chapter(
    chapter_title: str,
    project_id: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Récupère les chunks pertinents pour un chapitre.
    Utilisé par lesson_generator, exercise_generator et exam_generator.
    """
    # ✅ Requête enrichie — "Content related to:" est du bruit pour le modèle d'embedding
    query = (
        f"{chapter_title} — key concepts, definitions, formulas, "
        f"examples and exam questions"
    )
    return await retrieve_chunks(
        query=query,
        project_id=project_id,
        top_k=top_k,
    )