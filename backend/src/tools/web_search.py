"""web_search tool — Tavily search for facts outside the ingested filings.

For up-to-date or out-of-corpus context (recent news, a figure not in an
ingested filing). Uses the Tavily REST API directly via httpx (no extra SDK
dependency). When TAVILY_API_KEY is unset the tool returns an error observation
rather than raising, so the agent can fall back to its other tools and the loop
keeps running.
"""

from __future__ import annotations

import os

import httpx

from .spec import Tool

_TAVILY_URL = "https://api.tavily.com/search"
_MAX_RESULTS = 5
_TIMEOUT = 30


def web_search(query: str) -> str:
    """Search the web via Tavily; return a short list of titled snippets."""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return "Error: web_search unavailable (TAVILY_API_KEY not set). Use other tools."
    payload = {
        "api_key": api_key,
        "query": str(query),
        "max_results": _MAX_RESULTS,
        "search_depth": "basic",
        "include_answer": True,
    }
    try:
        resp = httpx.post(_TAVILY_URL, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Error: web_search request failed: {exc}"
    data = resp.json()
    parts = []
    if data.get("answer"):
        parts.append(f"Answer: {data['answer']}")
    for r in data.get("results", [])[:_MAX_RESULTS]:
        snippet = " ".join(str(r.get("content", "")).split())[:300]
        parts.append(f"- {r.get('title', '')} ({r.get('url', '')}): {snippet}")
    return "\n".join(parts) if parts else "No web results found."


TOOL = Tool(
    name="web_search",
    description="Search the web for facts not in the ingested filings (recent news, "
    "out-of-corpus figures). Returns titled snippets.",
    parameters={"query": "search query"},
    func=web_search,
)
