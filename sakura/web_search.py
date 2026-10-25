"""DuckDuckGo text + image search, ported from the Discord-era backend.

Blocking DDGS calls wrapped in asyncio.to_thread so they don't stall the event
loop. Sensitive-query blocklist + output scrubber are carried over verbatim.
No API keys required — DDGS is free.
"""
from __future__ import annotations

import asyncio
import re
from typing import List

from ddgs import DDGS


_BLOCKED_SEARCH_PATTERNS = [
    r'\bip\s*address\b', r'\bmy\s*ip\b', r'\bwhat\s*is\s*my\s*ip\b',
    r'\bip\s*lookup\b', r'\bip\s*location\b', r'\bgeolocat', r'\bgeolocation\b',
    r'\bwhois\b', r'\btraceroute\b', r'\bnetwork\s*address\b',
    r'\bhome\s*address\b', r'\bstreet\s*address\b', r'\bphysical\s*address\b',
    r'\bwhere\s*(do|does)\s*(i|you|he|she|they|we)\s*live\b',
    r'\bdox\b', r'\bdoxx\b', r'\bdoxing\b', r'\bdoxxing\b',
    r'\bssn\b', r'\bsocial\s*security\b', r'\bcredit\s*card\b',
    r'\bbank\s*account\b', r'\bpassword\b', r'\bphone\s*number\b',
    r'\breal\s*name\b', r'\bfull\s*name\b', r'\bpersonal\s*info\b',
]

_SCRUB_PATTERNS = [
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP REDACTED]'),
    (r'\b[0-9a-fA-F:]{7,39}\b', '[IP REDACTED]'),
    (r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE REDACTED]'),
    (r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b', '[SSN REDACTED]'),
    (r'\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b', '[CARD REDACTED]'),
]


def is_search_blocked(query: str) -> bool:
    q_lower = query.lower()
    for pattern in _BLOCKED_SEARCH_PATTERNS:
        if re.search(pattern, q_lower):
            return True
    return False


def _scrub(text: str) -> str:
    for pattern, replacement in _SCRUB_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def _web_search_sync(query: str, max_results: int = 5) -> str:
    try:
        if is_search_blocked(query):
            print(f"[SEARCH] BLOCKED sensitive query: {query!r}")
            return "(Search blocked: This query involves private/sensitive information that I cannot look up.)"
        print(f"[SEARCH] querying: {query!r}")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "(No search results found.)"
        formatted = []
        for i, r in enumerate(results, 1):
            title = _scrub(r.get("title", "No title"))
            body = _scrub(r.get("body", "No description"))
            url = r.get("href", "")
            formatted.append(f"{i}. **{title}**\n   {body}\n   Source: {url}")
        print(f"[SEARCH] {len(results)} results")
        return "\n\n".join(formatted)
    except Exception as e:
        print(f"[SEARCH] failed: {e!r}")
        return f"(Search failed: {e})"


def _image_search_sync(query: str, max_results: int = 5) -> List[str]:
    try:
        print(f"[IMG-SEARCH] querying: {query!r}")
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=max_results))
        urls = [r.get("image", "") for r in results if r.get("image")]
        print(f"[IMG-SEARCH] {len(urls)} images")
        return urls
    except Exception as e:
        print(f"[IMG-SEARCH] failed: {e!r}")
        return []


async def web_search(query: str, max_results: int = 5) -> str:
    return await asyncio.to_thread(_web_search_sync, query, max_results)


async def image_search(query: str, max_results: int = 5) -> List[str]:
    return await asyncio.to_thread(_image_search_sync, query, max_results)
