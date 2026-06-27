from __future__ import annotations

from .base import DiscoverySource, RawHit
from .ddg_search import DdgDiscoverySource

_DIRECTORY_DOMAINS = [
    "ycombinator.com",
    "techstars.com",
    "startupwiseguys.com",
    "500.co",
    "eu-startups.com",
    "dealroom.co",
]


class YcDirectorySource(DiscoverySource):
    name = "yc_directory"

    def __init__(self, rate_limit_s: float = 1.2, max_retries: int = 3):
        self._ddg = DdgDiscoverySource(rate_limit_s=rate_limit_s, max_retries=max_retries)

    def search(self, query: str, limit: int) -> list[RawHit]:
        hits: list[RawHit] = []
        per_domain = max(2, limit // len(_DIRECTORY_DOMAINS))
        for domain in _DIRECTORY_DOMAINS:
            scoped = f"{query} site:{domain} linkedin.com/in"
            for h in self._ddg.search(scoped, per_domain):
                h.source = self.name
                hits.append(h)
            if len(hits) >= limit:
                break
        return hits[:limit]
