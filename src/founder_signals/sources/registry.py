from __future__ import annotations

from ..config import Config
from .base import DiscoverySource, EnrichmentProvider
from .cached import CachedDiscoverySource, CachedEnrichmentProvider
from .ddg_search import DdgDiscoverySource
from .linkedin_provider import LinkedInProfileProvider
from .web_enrich import WebEnrichmentProvider
from .yc_directory import YcDirectorySource


def discovery_sources(cfg: Config) -> list[DiscoverySource]:
    if cfg.source_mode == "cached":
        return [CachedDiscoverySource()]
    return [
        DdgDiscoverySource(cfg.rate_limit_s, cfg.max_retries),
        YcDirectorySource(cfg.rate_limit_s, cfg.max_retries),
    ]


def enrichment_provider(cfg: Config) -> EnrichmentProvider:
    mode = cfg.enrichment_mode
    if mode == "auto":
        mode = "cached" if cfg.source_mode == "cached" else "web"

    if mode == "cached":
        return CachedEnrichmentProvider()
    if mode == "linkedin":
        return LinkedInProfileProvider()
    return WebEnrichmentProvider(cfg.request_timeout_s, cfg.rate_limit_s, cfg.user_agent)


def cached_discovery() -> DiscoverySource:
    return CachedDiscoverySource()
