from __future__ import annotations

import re
import time

from .base import DiscoverySource, RawHit

_LINKEDIN_RE = re.compile(r"https?://([a-z]{2,3}\.)?linkedin\.com/in/[^\s/?#]+", re.I)
_TITLE_SPLIT = re.compile(r"\s+[-|–]\s+")


class DdgDiscoverySource(DiscoverySource):
    name = "ddg_search"

    def __init__(self, rate_limit_s: float = 1.2, max_retries: int = 3):
        self.rate_limit_s = rate_limit_s
        self.max_retries = max_retries

    def search(self, query: str, limit: int) -> list[RawHit]:
        try:
            from ddgs import DDGS
        except Exception:  # pragma: no cover - dependency missing
            return []

        hits: list[RawHit] = []
        attempt = 0
        while attempt < self.max_retries:
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=limit):
                        hit = self._to_hit(r)
                        if hit:
                            hits.append(hit)
                break
            except Exception:
                attempt += 1
                time.sleep(self.rate_limit_s * attempt)
        time.sleep(self.rate_limit_s)
        return hits

    def _to_hit(self, r: dict) -> RawHit | None:
        href = r.get("href") or r.get("url") or ""
        title = r.get("title") or ""
        body = r.get("body") or ""
        m = _LINKEDIN_RE.search(href) or _LINKEDIN_RE.search(body)
        url = m.group(0) if m else (href or None)
        if not url:
            return None
        name = _TITLE_SPLIT.split(title)[0].strip() if title else None
        return RawHit(name=name or None, url=url,
                      snippet=f"{title}. {body}".strip(), source=self.name)
