from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import load_config
from .logging_utils import make_logger
from .pipeline import extract, normalize
from .pipeline.discover import _hit_to_profile, build_queries
from .pipeline.history import snapshot_fixture
from .pipeline.rank import score_profile
from .sources.ddg_search import DdgDiscoverySource
from .sources.web_enrich import WebEnrichmentProvider
from .store import Store

REGIONS = ("turkiye", "cee", "caucasus")
FIXTURE = Path(__file__).resolve().parent / "sources" / "fixtures" / "founders_seed.json"

_BAD_NAME_TOKENS = {
    "startup", "founder", "co-founder", "cofounder", "ceo", "cto", "fintech",
    "saas", "ai", "ml", "healthtech", "logistics", "climate", "gaming",
    "gastronomi", "food", "tech", "ventures", "capital", "group", "company",
    "solutions", "consulting", "linkedin", "profile",
}

_NON_FOUNDER_HEADLINE = (
    "general partner", "venture partner", "managing partner", "venture capital",
    " vc ", "vc |", "angel investor", "investor relations", "limited partner",
    "recruiter", "talent acquisition", "hr ", "human resources",
    "student", "intern", "professor", "phd candidate", "copywriter",
    "consultant at", "specialist", "association", "dernek", "federation",
    "freelance", "looking for", "aday adayı",
)


def _is_founder_headline(text: str) -> bool:
    low = (text or "").lower()
    return not any(bad in low for bad in _NON_FOUNDER_HEADLINE)


def _looks_like_person(name: str | None) -> bool:
    if not name:
        return False
    name = name.strip()
    if any(ch.isdigit() for ch in name) or "&" in name or "|" in name:
        return False
    toks = name.split()
    if not (2 <= len(toks) <= 4):
        return False
    if any(bad in name.lower().split() for bad in _BAD_NAME_TOKENS):
        return False
    return all(t[:1].isalpha() for t in toks)


def _identity(p) -> str:
    fold = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731
    return fold(p.full_name.value) + "|" + fold(p.current_company.value)


def _unique_inscope(store: Store) -> dict[str, list]:
    seen_url, seen_person, out = set(), set(), {r: [] for r in REGIONS}
    for p in store.all():
        reg = p.region.value
        if reg not in REGIONS or not p.linkedin_url or p.linkedin_url in seen_url:
            continue
        if not _looks_like_person(p.full_name.value):
            continue
        if not _is_founder_headline(p.headline.value or p.raw_snippet or ""):
            continue
        ident = _identity(p)
        if p.current_company.value and ident in seen_person:
            continue
        seen_url.add(p.linkedin_url)
        if p.current_company.value:
            seen_person.add(ident)
        out[reg].append(p)
    for reg in out:
        out[reg].sort(key=lambda p: 0 if p.is_founder.value is True else 1)
    return out


def _search_one(query: str, n: int) -> list:
    return DdgDiscoverySource(rate_limit_s=0.0, max_retries=2).search(query, n)


def run_capture(target: int = 100, max_seconds: int = 360, workers: int = 8) -> dict:
    # Capture more than the final target so export can still filter and rank.
    pool_target = int(target * 1.4)
    cfg = load_config()
    store = Store(cfg.store_path)
    store.clear()
    logger = make_logger(cfg.runs_dir, echo=False)

    per_region_q = {r: build_queries(r, max_queries=60) for r in REGIONS}
    interleaved = []
    for i in range(max(len(q) for q in per_region_q.values())):
        for r in REGIONS:
            if i < len(per_region_q[r]):
                interleaved.append((r, per_region_q[r][i]))

    start = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(_search_one, q, cfg.results_per_query): q
               for _reg, q in interleaved}
    done = 0
    for fut in as_completed(futures):
        done += 1
        try:
            hits = fut.result()
        except Exception:
            hits = []
        for hit in hits:
            p = _hit_to_profile(hit)
            if not store.get(p.id):
                store.upsert(p)
        check_every = max(2, workers // 2)
        if done % check_every == 0 or done == len(futures):
            # Re-run lightweight stages while search is still running to know when to stop.
            extract.run_extract(store, logger)
            normalize.run_normalize(store, logger)
            b = _unique_inscope(store)
            total = sum(len(v) for v in b.values())
            founders = sum(1 for r in REGIONS for p in b[r] if p.is_founder.value is True)
            print(f"[{done}/{len(futures)}] tr={len(b['turkiye'])} cee={len(b['cee'])} "
                  f"cauc={len(b['caucasus'])} total={total} founders={founders} "
                  f"elapsed={int(time.monotonic()-start)}s", file=sys.stderr, flush=True)
            if founders >= pool_target or time.monotonic() - start > max_seconds:
                break
    pool.shutdown(wait=False, cancel_futures=True)
    extract.run_extract(store, logger)
    normalize.run_normalize(store, logger)

    buckets = _unique_inscope(store)

    def _round_robin(pick) -> list:
        # Keep the fixture balanced across regions instead of taking one region first.
        out, idx = [], {r: 0 for r in REGIONS}
        remaining = True
        while len(out) < pool_target and remaining:
            remaining = False
            for reg in REGIONS:
                lst = buckets[reg]
                while idx[reg] < len(lst):
                    p = lst[idx[reg]]; idx[reg] += 1
                    if pick(p):
                        out.append((reg, p)); remaining = True
                        break
                if len(out) >= pool_target:
                    break
        return out

    candidates = _round_robin(lambda p: p.is_founder.value is True)
    if len(candidates) < pool_target:
        candidates += _round_robin(
            lambda p: p.is_founder.value is not True)[:pool_target - len(candidates)]
    candidates.sort(key=lambda rp: score_profile(rp[1]), reverse=True)
    chosen = candidates[:target]

    enricher = WebEnrichmentProvider(cfg.request_timeout_s, 0.0, cfg.user_agent)
    print(f"enriching {len(chosen)} founders (public web)...", file=sys.stderr, flush=True)

    def _enrich(item):
        reg, p = item
        try:
            e = enricher.enrich(p.full_name.value or "", p.current_company.value,
                                p.linkedin_url)
        except Exception:
            e = None
        return reg, p, e

    with ThreadPoolExecutor(max_workers=workers) as epool:
        results = list(epool.map(_enrich, chosen))

    seeds = []
    for reg, p, e in results:
        seeds.append({
            "name": p.full_name.value,
            "url": p.linkedin_url,
            "snippet": p.raw_snippet or "",
            "region": reg,
            "company": p.current_company.value or (e.company if e else None),
            "sectors": (e.sectors if e else []) or [],
            "company_stage": (e.company_stage if e else None),
            "other_links": (e.other_links if e else []) or [],
            "enrich_confidence": round(e.confidence, 3) if e else 0.0,
        })
    by_region = {r: sum(1 for s in seeds if s["region"] == r) for r in REGIONS}
    n_enriched = sum(1 for s in seeds if s["sectors"] or s["company_stage"])

    # Save the old fixture as the diff baseline before replacing it.
    snapped = snapshot_fixture(FIXTURE, cfg.history_dir)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(seeds, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {"seeds": len(seeds), "by_region": by_region, "enriched": n_enriched,
               "baselined_prior": snapped, "fixture": str(FIXTURE),
               "elapsed_s": int(time.monotonic() - start)}
    print(f"WROTE {len(seeds)} seeds {by_region}, {n_enriched} enriched; "
          f"baselined {snapped} prior -> {FIXTURE}", file=sys.stderr, flush=True)
    return summary
