"""Shared HTTP clients for the backend's calls to the STT service, OpenRouter and Ollama.

A new ``httpx.AsyncClient`` builds an SSL context and a connection pool, about 0.1 s per call on Windows, so
stt_client.py and llm.py keep one client per base URL (scheme + host + port) instead of one per call. A client is
created on first use, inside the running event loop, and server.py's shutdown hook closes them all (aclose_all).
Callers pass their own timeout with every request, exactly as they did per client. Cookies are never kept, so each
request goes out as it did from a fresh client; idle connections are dropped after 4 s, before uvicorn's 5 s
keep-alive limit (the STT service) closes them from the other side.
"""
from __future__ import annotations

import asyncio
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlsplit

import httpx

_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=4.0)
_clients: dict[str, tuple[httpx.AsyncClient, asyncio.AbstractEventLoop]] = {}


def base_of(url: str) -> str:
    """'http://127.0.0.1:50000/api/v1/asr' -> 'http://127.0.0.1:50000'."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def client(url: str) -> httpx.AsyncClient:
    """The shared client for the base URL of ``url``. A client made in an event loop that has since ended (another
    asyncio.run) is replaced, since its connections belong to that loop."""
    loop = asyncio.get_running_loop()
    key = base_of(url)
    hit = _clients.get(key)
    if hit is not None and hit[1] is loop and not hit[0].is_closed:
        return hit[0]
    c = httpx.AsyncClient(limits=_LIMITS, cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])))
    _clients[key] = (c, loop)
    return c


async def aclose_all() -> None:
    """Close every client made in the running loop (server shutdown)."""
    loop = asyncio.get_running_loop()
    items = list(_clients.values())
    _clients.clear()
    for c, owner in items:
        if owner is loop and not c.is_closed:
            try:
                await c.aclose()
            except Exception:  # noqa: BLE001 — shutting down anyway
                pass
