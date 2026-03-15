"""
src/tools/web_search.py
Web search tool for OttO — TRIAL FEATURE.

To disable entirely:
  1. Remove the import line in tools_registry.py
  2. Remove "search_web" from TOOL_IMPLEMENTATIONS and TOOL_SCHEMAS

Uses Tavily Search API (https://tavily.com).
Requires TAVILY_API_KEY in .env
"""

import os
import logging
from tavily import TavilyClient

log = logging.getLogger(__name__)


def search_web(query: str) -> dict:
    """
    Search the web for EV and automotive knowledge questions that are not
    covered by the dealership database — e.g. infotainment specs, safety
    ratings, charging compatibility, feature details.

    Returns a short answer and up to 3 source snippets.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {"error": "Web search unavailable — TAVILY_API_KEY not configured."}

    try:
        client = TavilyClient(api_key=api_key)
        result = client.search(
            query=query,
            search_depth="basic",      # "basic" is faster; "advanced" is more thorough
            max_results=3,
            include_answer=True,       # Tavily generates a direct answer summary
        )

        answer   = result.get("answer", "")
        snippets = [
            {"source": r.get("url", ""), "content": r.get("content", "")[:300]}
            for r in result.get("results", [])
        ]

        log.info(f"Web search: '{query}' → {len(snippets)} results")
        return {"answer": answer, "sources": snippets}

    except Exception as e:
        log.error(f"Web search failed: {e}")
        return {"error": f"Search failed: {str(e)}"}
