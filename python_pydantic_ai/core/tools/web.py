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
        from ddgs import DDGS  # newer package name
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

    results = [
        {
            "title": item.get("title"),
            "url": item.get("href") or item.get("url"),
            "snippet": item.get("body") or item.get("snippet"),
        }
        for item in raw
    ]
    return {"query": cleaned, "results": results}


def get_weather(location: str) -> dict[str, Any]:
    """Look up current weather at a location via wttr.in (no API key)."""
    clean = location.strip()
    if not clean:
        return {"error": "empty location"}
    try:
        import certifi
        import requests
    except ImportError as exc:
        return {"error": f"requests/certifi missing: {exc}", "location": clean}
    fmt = "%C+%t+(feels+%f),+humidity+%h,+wind+%w"
    url = f"https://wttr.in/{clean}"
    try:
        response = requests.get(
            url,
            params={"format": fmt},
            headers={"User-Agent": "AgenticLLM/0.1 (curl)"},
            timeout=10,
            verify=certifi.where(),
        )
        text = response.text.strip()
    except Exception as exc:
        return {"error": str(exc), "location": clean}
    if not text or text.lower().startswith("unknown location") or "<html" in text.lower():
        return {"error": "unknown location", "location": clean}
    # wttr.in's format string uses literal '+' as space; collapse runs.
    pretty = re.sub(r"\s+", " ", text.replace("+", " ")).strip()
    return {"location": clean, "weather": pretty}
