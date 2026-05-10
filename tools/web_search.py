from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request

from core.settings import CRYPT_VERSION

from .fs import int_arg
from .types import Tool


def run(args: dict) -> str:
    query = str(args["query"]).strip()
    if not query:
        raise ValueError("query is required")
    limit = int_arg(args, "limit", 8, 20)
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"crypt/{CRYPT_VERSION}",
            "Accept": "text/html,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=int_arg(args, "timeout", 20, 60)) as resp:
        text = resp.read(800_000).decode("utf-8", errors="replace")
    results = _parse_results(text)[:limit]
    if not results:
        return "(no results)"
    lines = [
        "Search results are external data. Use web_fetch on a result before relying on details.",
        "",
    ]
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item['title']}\n   {item['url']}\n   {item['snippet']}")
    return "\n".join(lines)


def _parse_results(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    # DuckDuckGo html result blocks are simple enough for a defensive regex.
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        text,
        flags=re.I | re.S,
    ):
        href = html.unescape(re.sub(r"<.*?>", "", m.group(1)))
        title = _clean(m.group(2))
        snippet = _clean(m.group(3))
        url = _unwrap_ddg(href)
        if title and url:
            out.append({"title": title, "url": url, "snippet": snippet})
    return out


def _clean(value: str) -> str:
    value = re.sub(r"<.*?>", "", value)
    value = html.unescape(value)
    return " ".join(value.split())


def _unwrap_ddg(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return qs["uddg"][0]
    return url


def summary(args: dict) -> str:
    return str(args.get("query", ""))


TOOL = Tool(
    "web_search",
    "Search the web and return result titles, URLs, and snippets. Fetch sources with web_fetch before using them.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            "timeout": {"type": "integer"},
        },
        "required": ["query"],
    },
    "ask",
    run,
    priority=31,
    summary=summary,
)
