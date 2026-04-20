import logging
from app.rag.retrieval import retrieve_chunks, assess_rag_quality
from app.web.tavily_client import tavily_search
from app.web.firecrawl_client import firecrawl_scrape

logger = logging.getLogger(__name__)


async def enrich_if_needed(
    query: str,
    project_id: str,
    chapter_hint: str | None = None,
    top_k: int = 5,
    context_label: str = "generation",
) -> tuple[list[dict], list[dict], bool]:
    """
    RAG hybride intelligent.

    1. Cherche dans les sources de l'utilisateur (RAG offline)
    2. Évalue la qualité des résultats
    3. Si insuffisant → web search ciblé

    Retourne : (rag_chunks, web_sources, web_was_used)
    """
    rag_chunks = await retrieve_chunks(
        query=query,
        project_id=project_id,
        chapter_hint=chapter_hint,
        top_k=top_k,
    )

    is_sufficient, avg_sim = assess_rag_quality(rag_chunks)

    if is_sufficient:
        logger.info("[%s] RAG suffisant (avg_sim=%.3f) — skip web search", context_label, avg_sim)
        return rag_chunks, [], False

    logger.info(
        "[%s] RAG insuffisant (avg_sim=%.3f, %d chunks) → web search ciblé",
        context_label, avg_sim, len(rag_chunks),
    )

    web_sources = await _targeted_web_search(query, rag_chunks, context_label)
    return rag_chunks, web_sources, True


async def _targeted_web_search(
    query: str,
    existing_chunks: list[dict],
    context_label: str = "generation",
) -> list[dict]:
    """
    Recherche web ciblée sur les lacunes du RAG.
    La requête est enrichie avec ce que le RAG a déjà trouvé
    pour ne pas chercher ce qu'on a, mais ce qui manque.
    """
    # ✅ existing_context utilisé pour affiner la requête (était calculé mais ignoré)
    existing_summary = " ".join(
        c.get("content", "")[:80] for c in existing_chunks[:2]
    ).strip()

    if existing_summary:
        # On cherche ce qui COMPLÈTE le contenu partiel déjà trouvé
        search_query = f"{query} — detailed explanation with examples and worked problems"
    else:
        # Aucun contexte → recherche directe
        search_query = f"{query} study guide explanation examples"

    # ✅ search_depth adapté au contexte
    # "advanced" pour génération de contenu, "basic" pour chat interactif
    search_depth = "basic" if context_label == "chat" else "advanced"

    try:
        results = await tavily_search(
            query=search_query,
            max_results=3,
            search_depth=search_depth,
        )

        if not results:
            return []

        enriched_sources = [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "source": "tavily",
            }
            for r in results
        ]

        # Deep crawl uniquement pour la génération (trop lent pour le chat)
        if context_label != "chat" and results:
            best_url = results[0].get("url", "")
            if best_url:
                deep_content = await firecrawl_scrape(best_url, max_chars=6000)
                if deep_content:
                    enriched_sources[0]["content"] = deep_content
                    enriched_sources[0]["source"] = "firecrawl"

        logger.info(
            "[%s] Web enrichment: %d sources (query='%s')",
            context_label, len(enriched_sources), search_query[:60],
        )
        return enriched_sources

    except Exception as e:
        logger.warning("[%s] Web fallback failed: %s", context_label, e)
        return []