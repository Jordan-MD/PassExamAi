import asyncio
import logging
from firecrawl import FirecrawlApp

from app.core.config import settings
from app.web.tavily_client import tavily_search

logger = logging.getLogger(__name__)

# ── Singleton client (thread-safe en lecture) ──────────────────────────────
_client: FirecrawlApp | None = None  # ✅ déclaré au niveau module


def get_firecrawl_client() -> FirecrawlApp:
    global _client
    if _client is None:
        _client = FirecrawlApp(api_key=settings.firecrawl_api_key)
    return _client


async def firecrawl_scrape(url: str, max_chars: int = 8000) -> str:
    """
    Extrait le contenu Markdown propre d'une URL.
    Utilise asyncio.to_thread() pour ne pas bloquer l'event loop (SDK sync).

    Retourne le contenu tronqué à max_chars, ou "" si échec.
    """
    client = get_firecrawl_client()
    try:
        # ✅ asyncio.to_thread() — remplace get_event_loop() déprécié en 3.10+
        result = await asyncio.to_thread(
            client.scrape_url,
            url,
            formats=["markdown"],
            only_main_content=True,
        )
        content: str = result.get("markdown", "") or ""
        truncated = content[:max_chars]
        logger.info(
            f"Firecrawl scrape '{url[:60]}' → {len(truncated)}/{len(content)} chars"
        )
        return truncated

    except Exception as e:
        logger.warning(f"Firecrawl error for '{url}': {e}")
        return ""  # ✅ toujours str, jamais None


async def enrich_with_web(
    queries: list[str],
    max_urls_to_crawl: int = 2,
    search_depth: str = "advanced",
) -> list[dict]:
    """
    Pipeline d'enrichissement web hybride :
    1. Tavily search → snippets rapides pour toutes les queries
    2. Firecrawl deep crawl → contenu complet sur les N meilleures URLs

    Retourne : [{url, title, content, source: 'tavily'|'firecrawl'}]

    Utilisé par roadmap_generator et lesson_generator (enrichissement offline).
    Pour le chat, utiliser gap_detector.enrich_if_needed() à la place.
    """
    all_sources: list[dict] = []
    seen_urls: set[str] = set()

    # ── 1. Tavily search pour chaque query ──────────────────────────────────
    # On lance toutes les recherches en parallèle
    search_tasks = [
        tavily_search(query=q, max_results=3, search_depth=search_depth)
        for q in queries
    ]
    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    for results in search_results:
        if isinstance(results, Exception):
            logger.warning(f"Tavily search failed: {results}")
            continue
        for r in results:
            url = r.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            all_sources.append({
                "url": url,
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "source": "tavily",
            })

    # ── 2. Firecrawl deep crawl sur les N meilleures URLs ──────────────────
    urls_to_crawl = list(seen_urls)[:max_urls_to_crawl]

    crawl_tasks = [firecrawl_scrape(url) for url in urls_to_crawl]
    crawl_results = await asyncio.gather(*crawl_tasks)

    url_to_content = dict(zip(urls_to_crawl, crawl_results))

    for source in all_sources:
        deep = url_to_content.get(source["url"])
        if deep:
            source["content"] = deep
            source["source"] = "firecrawl"

    logger.info(
        f"Web enrichment: {len(all_sources)} sources "
        f"({len(urls_to_crawl)} crawlées via Firecrawl)"
    )
    return all_sources