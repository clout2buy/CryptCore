"""Browser operation planning and local WebUI smoke checks."""
from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrowserPlan:
    mode: str
    actions: tuple[str, ...] = ()
    target: str = ""
    needs_visual_browser: bool = False
    reason: str = ""


@dataclass(frozen=True)
class BrowserSmokeResult:
    url: str
    ok: bool
    status: int = 0
    title: str = ""
    bytes_read: int = 0
    error: str = ""
    checks: list[str] = field(default_factory=list)


def plan(text: str, *, target: str = "") -> BrowserPlan:
    lower = " ".join(str(text or "").lower().split())
    actions: list[str] = []
    if any(term in lower for term in ("search", "look up", "find online", "latest")):
        actions.append("search")
    if any(term in lower for term in ("read", "open", "page", "url", "website")):
        actions.append("read-page")
    if any(term in lower for term in ("screenshot", "visual", "see what", "looks like", "mobile", "desktop")):
        actions.append("screenshot")
    if any(term in lower for term in ("extract", "scrape", "structured", "table", "links")):
        actions.append("extract")
    if "localhost" in lower or "127.0.0.1" in lower or "webui" in lower:
        actions.append("local-qa")
    if not actions:
        actions.append("read-page" if target else "search")
    needs_visual = "screenshot" in actions or "local-qa" in actions
    mode = "local-app-qa" if "local-qa" in actions else "research" if "search" in actions else "browser-read"
    return BrowserPlan(
        mode=mode,
        actions=tuple(dict.fromkeys(actions)),
        target=target,
        needs_visual_browser=needs_visual,
        reason="browser lane selected from prompt terms",
    )


def local_smoke(url: str, *, timeout: float = 3.0) -> BrowserSmokeResult:
    checks: list[str] = []
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - caller supplies local/test URL
            status = int(getattr(response, "status", 0) or 0)
            body = response.read(200_000)
    except Exception as exc:
        return BrowserSmokeResult(url=url, ok=False, error=f"{type(exc).__name__}: {exc}", checks=["http"])
    text = body.decode("utf-8", errors="replace")
    title = _title(text)
    checks.append("http")
    if "<html" in text.lower():
        checks.append("html")
    if title:
        checks.append("title")
    return BrowserSmokeResult(
        url=url,
        ok=200 <= status < 400 and bool(text),
        status=status,
        title=title,
        bytes_read=len(body),
        checks=checks,
    )


def _title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return ""
    return " ".join(match.group(1).split())[:160]
