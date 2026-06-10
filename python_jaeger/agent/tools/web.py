"""Network skills.

  • web_search(query, max_results)  — DuckDuckGo HTML search (no API key)
  • get_weather(location)           — wttr.in lookup (no API key)
"""

from __future__ import annotations

import re
from typing import Any


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """DuckDuckGo HTML search. No API key required."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return {"error": "duckduckgo-search not installed", "query": query}

    cleaned = query.strip()
    if not cleaned:
        return {"error": "empty query"}
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(cleaned, max_results=max_results))
    except Exception as exc:
        return {"error": str(exc), "query": cleaned}
    return {
        "query": cleaned,
        "results": [
            {
                "title": r.get("title"),
                "url": r.get("href") or r.get("url"),
                "snippet": r.get("body") or r.get("snippet"),
            }
            for r in raw
        ],
    }


def get_weather(location: str) -> dict[str, Any]:
    """Look up current weather at a named location via wttr.in (no API key)."""
    clean = location.strip()
    if not clean:
        return {"error": "empty location"}
    try:
        import certifi
        import requests
    except ImportError as exc:
        return {"error": f"requests/certifi missing: {exc}", "location": clean}
    fmt = "%C+%t+(feels+%f),+humidity+%h,+wind+%w"
    try:
        response = requests.get(
            f"https://wttr.in/{clean}",
            params={"format": fmt},
            headers={"User-Agent": "Jaeger/1.0"},
            timeout=10,
            verify=certifi.where(),
        )
        text = response.text.strip()
    except Exception as exc:
        return {"error": str(exc), "location": clean}
    if not text or text.lower().startswith("unknown location") or "<html" in text.lower():
        return {"error": "unknown location", "location": clean}
    pretty = re.sub(r"\s+", " ", text.replace("+", " ")).strip()
    return {"location": clean, "weather": pretty}
