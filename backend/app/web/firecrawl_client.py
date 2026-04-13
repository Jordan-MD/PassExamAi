import logging
import asyncio
from firecrawl import FirecrawlApp

from app.web.tavily_client import tavily_search
from app.core.config import settings


logger = logging.getLogger(__name__)

def get_firecrawl_client() -> FirecrawlApp:
    global _client
    if _client is None:
        _client = FirecrawlApp(api_key=settings.firecrawl_api_key)
    return _client


async def firecrawl_scrape(url: str, max_chars: int = 8000) -> str:
    """
    Extrait le contenu complet d'une page web en Markdown propre.
    Utilisé pour les pages éducatives riches (cours, tutoriels, docs).
    
    max_chars : limite la taille pour gérer le budget de tokens LLM.
    Retourne le contenu Markdown ou chaîne vide en cas d'échec.
    """
    
    client = get_firecrawl_client()
    try:
        # Run sync dans un thread pour ne pas bloquer l'event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: client.scrape_url(url, formats=["markdown"], only_main_content=True)
        )
        content = result.get("markdown", "") or ""
        return content[:max_chars]
    except Exception as e:
        logger.warning(f"Firecrawl error for {url}: {e}")

async def enrich_with_web(
    queries: list[str],
    max_urls_to_crawl: int = 2,
    search_depth: str = "advanced",
) -> list[dict]:
    """
    Pipeline complet d'enrichissement web :
    1. Recherche Tavily pour chaque query → récupère les top URLs
    2. Crawl Firecrawl sur les max_urls_to_crawl meilleures URLs
    
    Retourne une liste de {url, title, content, source: 'tavily'|'firecrawl'}
    
    Utilisé par : roadmap_generator, lesson_generator
    """

    all_sources = []
    seen_urls: set[str] = set()

    for query in queries:
        results = await tavily_search(
            query=query,
            max_results=3,
            search_depth=search_depth,
        )

        for result in results:
            url = result.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Snippet Tavily = contexte rapide
            all_sources.append({
                "url": url,
                "title": result.get("title", ""),
                "content": result.get("content", ""),
                "source": "tavily",
            })

    # Crawl les N meilleures URLs avec Firecrawl pour plus de profondeur
    urls_to_crawl = list(seen_urls)[:max_urls_to_crawl]
    for url in urls_to_crawl:
        deep_content = await firecrawl_scrape(url)
        if deep_content:
            # Remplace le snippet Tavily par le contenu complet
            for source in all_sources:
                if source["url"] == url:
                    source["content"] = deep_content
                    source["source"] = "firecrawl"
                    break

    logger.info(
        f"Web enrichment: {len(all_sources)} sources ({len(urls_to_crawl)} crawlées via Firecrawl)"
    )
    return all_sources