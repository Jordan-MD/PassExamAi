from app.db.supabase_client import supabase
from app.ai.llm_client import get_embeddings
from app.schemas.documents import DocumentChunk, ChunkMetadata
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


async def retrieve_chunks(
    query: str,
    project_id: str,
    chapter_hint: str | None = None,
    top_k: int | None = None,
) -> list[dict]:
    """
    Recherche les chunks les plus pertinents pour une requête.
    Filtre par project_id et optionnellement par chapter_hint.
    
    Retourne une liste de dicts : {content, metadata, similarity}
    """
    k = top_k or settings.top_k_retrieval

    # 1. Embed la requête
    query_embeddings = await get_embeddings([query])
    query_vector = query_embeddings[0]

    # 2. Construction du filtre metadata
    metadata_filter = {"project_id": project_id}
    if chapter_hint:
        metadata_filter["chapter_hint"] = chapter_hint

    try:
        # 3. Appel RPC Supabase pour la recherche vectorielle
        # On utilise une fonction SQL custom (voir migration ci-dessous)
        response = supabase.rpc(
            "match_document_chunks",
            {
                "query_embedding": query_vector,
                "match_count": k,
                "filter": metadata_filter,
            },
        ).execute()

        chunks = response.data or []
        logger.info(
            f"Retrieval pour '{query[:50]}...' → {len(chunks)} chunks trouvés"
        )
        return chunks

    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        return []


async def retrieve_for_chapter(
    chapter_title: str,
    project_id: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Récupère les chunks pertinents pour un chapitre spécifique.
    Utilisé par le générateur de leçons et d'exercices.
    """
    query = f"Content related to: {chapter_title}"
    return await retrieve_chunks(
        query=query,
        project_id=project_id,
        chapter_hint=chapter_title,
        top_k=top_k,
    )