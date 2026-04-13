from tavily import AsyncTavilyClient
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

_client: AsyncTavilyClient | None = None


def get_tavily_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        _client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    return _client


async def tavily_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",  # "basic" (rapide) ou "advanced" (qualité)
    include_raw_content: bool = False,
) -> list[dict]:
    """
    Recherche web optimisée pour les LLM.
    Retourne une liste de {title, url, content, score}.
    
    search_depth="basic"   → ~1s, idéal pour tuteur chat
    search_depth="advanced"→ ~3s, idéal pour génération roadmap/leçon
    """
    client = get_tavily_client()
    try:
        response = await client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_raw_content=include_raw_content,
        )
        results = response.get("results", [])
        logger.info(f"Tavily search '{query[:50]}' → {len(results)} résultats")
        return results

    except Exception as e:
        logger.error(f"Tavily search error: {e}")
        return []  # Dégradation gracieuse : on continue sans web


async def tavily_extract_url(url: str) -> str:
    """
    Extrait le contenu propre d'une URL unique via Tavily Extract.
    Plus rapide que Firecrawl pour les pages simples.
    Retourne le texte ou une chaîne vide en cas d'échec.
    """
    client = get_tavily_client()
    try:
        response = await client.extract(urls=[url])
        results = response.get("results", [])
        if results:
            raw = results[0].get("raw_content", "")
            logger.info(f"Tavily extract '{url[:60]}' → {len(raw)} chars")
            return raw
        return ""

    except Exception as e:
        logger.warning(f"Tavily extract error for {url}: {e}")
        return ""