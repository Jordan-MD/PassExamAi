import asyncio
import logging
from firecrawl import FirecrawlApp
from app.core.config import settings
from app.web.tavily_client import tavily_search

logger = logging.getLogger(__name__)
_client: FirecrawlApp | None = None


def get_firecrawl_client() -> FirecrawlApp:
    global _client
    if _client is None:
        _client = FirecrawlApp(api_key=settings.firecrawl_api_key)
    return _client

async def firecrawl_scrape(url: str, max_chars: int = 8000) -> str:
    client = get_firecrawl_client()
    try:
        def _do_scrape():
            if hasattr(client, "scrape"):
                return client.scrape(url, formats=["markdown"])
            else:
                # Fallback si le SDK est instancié différemment
                raise AttributeError("Le client Firecrawl ne possède ni 'scrape_url' ni 'scrape'")

        result = await asyncio.to_thread(_do_scrape)
        
        content = ""
        if result and isinstance(result, dict):
            # Selon la version, le markdown est à la racine ou dans 'data'
            content = result.get("markdown") or result.get("data", {}).get("markdown", "")
        
        return content[:max_chars] if content else ""

    except Exception as e:
        logger.error(f"Firecrawl Error for {url}: {srt(e)}")
        return ""


async def enrich_with_web(
    queries: list[str],
    max_urls_to_crawl: int = 2,
    search_depth: str = "advanced",
) -> list[dict]:
    """
    Pipeline d'enrichissement web : Tavily pour la recherche, Firecrawl pour le contenu profond.
    """
    all_sources: list[dict] = []
    seen_urls: set[str] = set()

    # 1. Recherche Tavily (Rapide)
    search_tasks = [
        tavily_search(query=q, max_results=3, search_depth=search_depth)
        for q in queries
    ]
    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    for results in search_results:
        if isinstance(results, Exception):
            continue
        for r in results:
            url = r.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            all_sources.append({
                "url": url,
                "title": r.get("title", "Sans titre"),
                "content": r.get("content", ""),
                "source": "tavily",
            })

    # 2. Scraping Firecrawl (Profond) sur les meilleures URLs
    urls_to_crawl = list(seen_urls)[:max_urls_to_crawl]
    crawl_tasks = [firecrawl_scrape(url) for url in urls_to_crawl]
    crawl_results = await asyncio.gather(*crawl_tasks)

    # Mise à jour des sources avec le contenu Markdown complet
    url_map = dict(zip(urls_to_crawl, crawl_results))
    for source in all_sources:
        deep_content = url_map.get(source["url"])
        if deep_content:
            source["content"] = deep_content
            source["source"] = "firecrawl"

    return all_sources