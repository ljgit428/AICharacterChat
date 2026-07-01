from urllib.parse import urlparse

import requests

from .models import WebSearchConfiguration


def _normalize_result(item):
    url = (item.get("url") or "").strip()
    title = (item.get("title") or url).strip()
    snippet = (item.get("content") or item.get("snippet") or "").strip()

    if not url:
        return None

    domain = urlparse(url).netloc.replace("www.", "")
    return {
        "title": title[:200],
        "url": url,
        "snippet": snippet[:500],
        "domain": domain,
        "source": "web_search",
    }


def _empty_search_result(query="", provider="", error=""):
    return {
        "query": query,
        "items": [],
        "provider": provider,
        "error": error,
    }


def _get_user_search_configuration(user=None, chat_session=None):
    resolved_user = user or getattr(chat_session, "user", None)
    if not resolved_user:
        return None
    return WebSearchConfiguration.get_for_user(resolved_user)


def search_web(query, user=None, chat_session=None, config=None):
    normalized_query = (query or "").strip()
    if not normalized_query:
        return _empty_search_result()

    resolved_config = config or _get_user_search_configuration(user=user, chat_session=chat_session)
    if not resolved_config:
        return _empty_search_result(
            query=normalized_query,
            error="Web search API is not configured. Add your Tavily API key in API Settings.",
        )

    provider = (resolved_config.provider or "").strip().lower()
    max_results = min(max(int(resolved_config.max_results or 5), 1), 10)

    if provider == "tavily":
        api_key = (resolved_config.api_key or "").strip()
        if not api_key:
            return _empty_search_result(
                query=normalized_query,
                provider="tavily",
                error="Tavily API key is missing. Update it in API Settings.",
            )

        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": normalized_query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return _empty_search_result(
                query=normalized_query,
                provider="tavily",
                error=f"Tavily search failed: {exc}",
            )

        payload = response.json()
        items = [
            normalized
            for normalized in (_normalize_result(item) for item in payload.get("results", []))
            if normalized
        ]
        return {
            "query": normalized_query,
            "items": items,
            "provider": "tavily",
            "error": "",
        }

    return _empty_search_result(
        query=normalized_query,
        provider=provider,
        error=f"Unsupported web search provider: {provider}",
    )
