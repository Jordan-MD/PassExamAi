import logging
from tavily import AsyncTavilyClient
from app.core.config import settings

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
    search_depth: str = "basic",
    include_raw_content: bool = False,
) -> list[dict]:
    """
    Recherche web optimisée LLM.
    Retourne [{title, url, content, score}] ou [] si échec.

    search_depth="basic"    → ~1s  — chat interactif
    search_depth="advanced" → ~3s  — génération de contenu
    """
    client = get_tavily_client()
    try:
        response = await client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_raw_content=include_raw_content,
        )
        results: list[dict] = response.get("results", [])
        logger.info(f"Tavily '{query[:50]}' → {len(results)} résultats")
        return results

    except Exception as e:
        logger.warning(f"Tavily search error: {e}")
        return []


async def tavily_extract_url(url: str) -> str:
    """
    Extraction du contenu brut d'une URL unique.
    Fallback léger avant Firecrawl.
    """
    client = get_tavily_client()
    try:
        response = await client.extract(urls=[url])
        results = response.get("results", [])
        raw: str = results[0].get("raw_content", "") if results else ""
        logger.info(f"Tavily extract '{url[:60]}' → {len(raw)} chars")
        return raw
    except Exception as e:
        logger.warning(f"Tavily extract error for '{url}': {e}")
        return ""