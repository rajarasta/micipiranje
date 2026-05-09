# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "httpx>=0.27",
#   "trafilatura>=1.12",
# ]
# ///
"""LM Studio web-search MCP server.

Exposes web_search / web_fetch / web_research tools that let a local LLM
running in LM Studio search the internet, read pages, and pull together a
research bundle for synthesis.

Backends: SearXNG (self-hosted) and Tavily. Selected via LM_WEB_BACKEND.
Page extraction: httpx + trafilatura (boilerplate-stripped markdown).
SSRF guard: only http/https, blocks private/loopback/link-local addresses
(except the configured SearXNG URL).
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura
from mcp.server.fastmcp import FastMCP


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


BACKEND = (_env("LM_WEB_BACKEND", "auto") or "auto").lower()
TAVILY_API_KEY = _env("TAVILY_API_KEY")
SEARXNG_URL = (_env("SEARXNG_URL", "http://127.0.0.1:8080") or "").rstrip("/")
TIMEOUT = float(_env("LM_WEB_TIMEOUT", "15") or "15")
MAX_BYTES = int(_env("LM_WEB_MAX_BYTES", "2000000") or "2000000")
CACHE_TTL = int(_env("LM_WEB_CACHE_TTL", "86400") or "86400")

_cache_dir_env = _env("LM_WEB_CACHE_DIR")
if _cache_dir_env:
    CACHE_DIR = Path(_cache_dir_env).resolve()
else:
    _mcp_root = _env("LM_MCP_ROOT")
    CACHE_DIR = (Path(_mcp_root) / ".web_cache" if _mcp_root else Path.cwd() / ".web_cache").resolve()
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_backend() -> str:
    if BACKEND == "tavily":
        if not TAVILY_API_KEY:
            raise RuntimeError("LM_WEB_BACKEND=tavily but TAVILY_API_KEY is not set")
        return "tavily"
    if BACKEND == "searxng":
        return "searxng"
    if BACKEND == "auto":
        return "tavily" if TAVILY_API_KEY else "searxng"
    raise RuntimeError(f"unknown LM_WEB_BACKEND={BACKEND!r}")


def _safe_url(url: str) -> str:
    """Reject non-http(s) and private/loopback addresses. SearXNG URL exempt."""
    if SEARXNG_URL and url.startswith(SEARXNG_URL):
        return url
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {p.scheme!r}")
    host = p.hostname
    if not host:
        raise ValueError("URL missing hostname")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {host}: {e}") from e
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError(f"refusing to fetch internal address {host} -> {addr}")
    return url


def _cache_key(*parts: str) -> Path:
    h = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{h}.json"


def _cache_get(path: Path) -> dict | None:
    if CACHE_TTL <= 0 or not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(path: Path, value: dict) -> None:
    if CACHE_TTL <= 0:
        return
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _rewrite_url(url: str) -> str:
    """Rewrite scraper-hostile URLs to friendlier server-rendered mirrors.

    Reddit's www/new domains return a JS shell to non-browsers; old.reddit.com
    returns proper server-rendered HTML that trafilatura can extract from.
    """
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host in ("www.reddit.com", "reddit.com", "new.reddit.com"):
        return p._replace(netloc="old.reddit.com").geturl()
    return url


async def _search_searxng(client: httpx.AsyncClient, query: str, n: int) -> list[dict]:
    if not SEARXNG_URL:
        raise RuntimeError("SEARXNG_URL is not configured")
    r = await client.get(
        f"{SEARXNG_URL}/search",
        params={"q": query, "format": "json", "safesearch": "0"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    out = []
    for item in data.get("results", [])[:n]:
        url = item.get("url")
        if not url:
            continue
        out.append({
            "title": item.get("title") or url,
            "url": url,
            "snippet": item.get("content") or "",
        })
    return out


async def _search_tavily(client: httpx.AsyncClient, query: str, n: int) -> list[dict]:
    r = await client.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": n,
            "search_depth": "advanced",
            "include_answer": False,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    out = []
    for item in data.get("results", [])[:n]:
        url = item.get("url")
        if not url:
            continue
        out.append({
            "title": item.get("title") or url,
            "url": url,
            "snippet": item.get("content") or "",
        })
    return out


async def _do_search(query: str, n: int) -> list[dict]:
    backend = _resolve_backend()
    cache_path = _cache_key("search", backend, query, str(n))
    cached = _cache_get(cache_path)
    if cached is not None:
        return cached["results"]
    async with httpx.AsyncClient(headers={"User-Agent": _BROWSER_UA}) as client:
        if backend == "tavily":
            results = await _search_tavily(client, query, n)
        else:
            results = await _search_searxng(client, query, n)
    _cache_put(cache_path, {"backend": backend, "query": query, "results": results})
    return results


async def _do_fetch(url: str) -> dict:
    url = _rewrite_url(url)
    _safe_url(url)
    cache_path = _cache_key("fetch", url)
    cached = _cache_get(cache_path)
    if cached is not None and (cached.get("content") or "").strip():
        return cached

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hr;q=0.8",
        },
        timeout=TIMEOUT,
    ) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            final_url = str(r.url)
            _safe_url(final_url)
            chunks: list[bytes] = []
            total = 0
            async for chunk in r.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    break
                chunks.append(chunk)
            html = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")

    extracted = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        with_metadata=True,
        favor_recall=True,
    ) or ""

    if not extracted.strip():
        # Main-content extractor found nothing (JS-shell page, login wall,
        # very atypical layout). Fall back to a coarse strip-tags pass so
        # the model gets *something* useful instead of an empty string.
        fallback = trafilatura.html2txt(html) or ""
        if fallback.strip():
            extracted = fallback

    title = ""
    meta = trafilatura.extract_metadata(html)
    if meta and getattr(meta, "title", None):
        title = meta.title

    result = {
        "url": url,
        "final_url": final_url,
        "title": title,
        "content": extracted,
    }
    if extracted.strip():
        _cache_put(cache_path, result)
    return result


mcp = FastMCP("lm-web")


@mcp.tool()
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web. Returns a list of {title, url, snippet} dicts.

    Uses the configured backend (Tavily if TAVILY_API_KEY is set, otherwise
    SearXNG at SEARXNG_URL). Best for when you want to see what's available
    before fetching specific pages. For end-to-end research, prefer
    web_research, which also fetches and cleans the top results."""
    if max_results < 1 or max_results > 20:
        raise ValueError("max_results must be between 1 and 20")
    return await _do_search(query, max_results)


@mcp.tool()
async def web_fetch(url: str, max_chars: int = 8000) -> dict:
    """Fetch one URL and extract its main content as clean markdown.

    Returns {url, final_url, title, content, truncated}. Strips nav, ads,
    and boilerplate via trafilatura. Use this to read a specific page the
    user mentioned, or to follow a link from web_search. The content is
    truncated to max_chars; the truncated flag tells you if it was."""
    data = await _do_fetch(url)
    content = data["content"] or ""
    truncated = len(content) > max_chars
    return {
        "url": data["url"],
        "final_url": data["final_url"],
        "title": data["title"],
        "content": content[:max_chars],
        "truncated": truncated,
    }


@mcp.tool()
async def web_research(question: str, num_sources: int = 5, max_chars_per_source: int = 4000) -> str:
    """One-shot research: search the web for `question`, fetch the top
    `num_sources` results in parallel, extract clean content from each, and
    return a single Markdown 'research bundle' with numbered citations.

    The model should then synthesize the answer from the bundle and cite
    sources by number, e.g. "[1]" or "[2]". Use this when the user asks a
    factual question that needs fresh info — it's higher quality than
    calling web_search + web_fetch yourself, because it parallelizes the
    fetches and gives the model a clean, deduplicated, citation-ready
    context to reason over."""
    if num_sources < 1 or num_sources > 10:
        raise ValueError("num_sources must be between 1 and 10")

    results = await _do_search(question, num_sources)
    if not results:
        return f"# Research bundle for: {question}\n\n_No search results._\n"

    fetches = await asyncio.gather(
        *[_do_fetch(r["url"]) for r in results],
        return_exceptions=True,
    )

    parts = [f"# Research bundle for: {question}\n"]
    for i, (meta, fetched) in enumerate(zip(results, fetches), start=1):
        title = meta.get("title") or meta["url"]
        if isinstance(fetched, Exception):
            parts.append(
                f"## [{i}] {title}\nSource: {meta['url']}\n\n_Fetch failed: {fetched}_\n\nSnippet from search:\n\n{meta.get('snippet', '')}\n\n---\n"
            )
            continue
        content = (fetched.get("content") or "").strip()
        if not content:
            content = meta.get("snippet") or "_No extractable content._"
        if len(content) > max_chars_per_source:
            content = content[:max_chars_per_source].rstrip() + "\n\n_…truncated._"
        parts.append(
            f"## [{i}] {fetched.get('title') or title}\nSource: {fetched.get('final_url') or meta['url']}\n\n{content}\n\n---\n"
        )
    return "\n".join(parts)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8090"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
