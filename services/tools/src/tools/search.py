from __future__ import annotations

import asyncio

from shared.logging import get_logger

logger = get_logger("tools.search")


async def web_search(query: str, max_results: int = 5) -> dict:
    try:
        from duckduckgo_search import DDGS

        loop = asyncio.get_running_loop()

        def _search() -> list[dict]:
            results: list[dict] = []
            with DDGS() as ddgs:
                for _, r in enumerate(ddgs.text(query, max_results=max_results)):
                    if not isinstance(r, dict):
                        continue
                    url = str(r.get("href", r.get("url", "")))
                    if not url.startswith(("http://", "https://")):
                        continue
                    results.append({
                        "title": str(r.get("title", "")),
                        "url": url,
                        "snippet": str(r.get("body", r.get("snippet", ""))),
                    })
                    if len(results) >= max_results:
                        break
            return results

        results = await loop.run_in_executor(None, _search)
        logger.info("web search completed", query=query, results=len(results))
        return {"results": results}

    except ImportError:
        logger.exception(
            "duckduckgo_search not installed; "
            "run: pip install duckduckgo_search"
        )
        return {
            "results": [],
            "error": "duckduckgo_search library not installed",
        }
    except Exception as e:
        logger.exception("web search failed", error=str(e))
        return {"results": [], "error": str(e)}
