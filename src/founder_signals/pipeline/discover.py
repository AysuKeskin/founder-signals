from __future__ import annotations

import time

from ..config import Config
from ..logging_utils import RunLogger
from ..schema import FieldValue, Profile, Stage, Status, ToolResult
from ..sources import registry
from ..sources.base import RawHit
from ..store import Store, profile_id

_ROLE_TERMS = ['"founder"', '"co-founder"', '"CEO"']
_REGION_TERMS = {
    "turkiye": ["Türkiye", "Istanbul", "Ankara"],
    "cee": ["Poland", "Romania", "Estonia", "Czechia", "Lithuania", "Warsaw"],
    "caucasus": ["Georgia", "Armenia", "Azerbaijan", "Tbilisi", "Yerevan"],
}
_SECTORS = ["fintech", "SaaS", "AI", "healthtech", "logistics", "climate", "gaming"]


def build_queries(region: str, max_queries: int) -> list[str]:
    regions = list(_REGION_TERMS) if region == "all" else [region]
    queries: list[str] = []
    for reg in regions:
        for geo in _REGION_TERMS.get(reg, []):
            for role in _ROLE_TERMS:
                for sector in _SECTORS:
                    queries.append(f"site:linkedin.com/in {role} {sector} startup {geo}")
    seen, out = set(), []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
        if len(out) >= max_queries:
            break
    return out


def _hit_to_profile(hit: RawHit) -> Profile:
    pid = profile_id(hit.url, hit.name, hit.extra.get("company"))
    p = Profile(id=pid, linkedin_url=hit.url, raw_snippet=hit.snippet)
    if hit.name:
        p.full_name = FieldValue(value=hit.name, source=hit.source,
                                 source_url=hit.url, confidence=0.6)
    if hit.url:
        p.source_urls = [hit.url]
    p.mark_stage(Stage.DISCOVER)
    return p


def run_discover(cfg: Config, store: Store, logger: RunLogger,
                 region: str = "all", limit: int = 300,
                 max_queries: int = 40) -> ToolResult[dict]:
    start = time.monotonic()
    sources = registry.discovery_sources(cfg)
    queries = build_queries(region, max_queries)

    all_hits: list[RawHit] = []
    with logger.stage(Stage.DISCOVER.value, region=region, queries=len(queries)):
        for q in queries:
            if len(all_hits) >= limit:
                break
            for src in sources:
                hits = src.search(q, cfg.results_per_query)
                logger.log("discover_query", source=src.name, query=q, hits=len(hits))
                all_hits.extend(hits)
                if len(all_hits) >= limit:
                    break

        if not all_hits and cfg.source_mode == "auto":
            logger.log("discover_fallback", reason="no_live_hits", source="cached")
            cached = registry.cached_discovery()
            for q in queries[:20]:
                all_hits.extend(cached.search(q, cfg.results_per_query))

    new, existing = 0, 0
    for hit in all_hits[: limit if limit else None]:
        p = _hit_to_profile(hit)
        prior = store.get(p.id)
        if prior:
            for u in p.source_urls:
                if u not in prior.source_urls:
                    prior.source_urls.append(u)
            if not prior.raw_snippet:
                prior.raw_snippet = p.raw_snippet
            if not prior.full_name.value and p.full_name.value:
                prior.full_name = p.full_name
            prior.mark_stage(Stage.DISCOVER)
            store.upsert(prior)
            existing += 1
        else:
            store.upsert(p)
            new += 1

    elapsed = int((time.monotonic() - start) * 1000)
    data = {"queries": len(queries), "raw_hits": len(all_hits),
            "new": new, "existing": existing, "total_in_store": store.count()}
    status = Status.OK if new or existing else Status.PARTIAL
    return ToolResult(status=status, stage=Stage.DISCOVER, data=data,
                      count=new, run_id=logger.run_id, elapsed_ms=elapsed,
                      provenance=[s.name for s in sources],
                      message=f"discovered {new} new, {existing} existing")
