from __future__ import annotations

import time

from ..config import Config
from ..logging_utils import RunLogger
from ..schema import FieldValue, Profile, ProfileError, Stage, ToolResult, stage_status
from ..sources import registry
from ..store import Store
from .extract import _real_company


def _enrich_one(p: Profile, provider) -> Profile:
    name = p.full_name.value or ""
    company = p.current_company.value
    data = provider.enrich(name, company, p.linkedin_url)

    cand = _real_company(data.company, name) if data.company else None
    if cand and not p.current_company.value:
        p.current_company = FieldValue(value=cand, source=provider.name,
                                       source_url=data.source_url,
                                       confidence=min(data.confidence, 0.5))
    if data.sectors:
        existing = p.sectors.value if isinstance(p.sectors.value, list) else []
        merged_sec = sorted(set(existing) | set(data.sectors))
        p.sectors = FieldValue(value=merged_sec, source=provider.name,
                               source_url=data.source_url, confidence=data.confidence)
    if data.company_stage and not p.company_stage.value:
        p.company_stage = FieldValue(value=data.company_stage, source=provider.name,
                                     source_url=data.source_url, confidence=data.confidence)
    if data.education:
        p.education = FieldValue(value=data.education, source=provider.name,
                                 confidence=data.confidence)
    if data.other_links:
        merged = list(dict.fromkeys((p.other_links.value or []) + data.other_links)) \
            if isinstance(p.other_links.value, list) else data.other_links
        p.other_links = FieldValue(value=merged, source=provider.name,
                                   confidence=data.confidence)
        for link in data.other_links:
            if link not in p.source_urls:
                p.source_urls.append(link)

    if data.confidence > 0:
        vals = [fv.confidence for _, fv in p.field_items() if fv.value is not None]
        p.overall_confidence = round(min(sum(vals) / len(vals) + 0.05, 1.0), 3) if vals else data.confidence
    p.mark_stage(Stage.ENRICH)
    return p


def run_enrich(cfg: Config, store: Store, logger: RunLogger,
               only_pending: bool = True, in_scope_only: bool = True) -> ToolResult[dict]:
    start = time.monotonic()
    provider = registry.enrichment_provider(cfg)
    profiles = store.needing_stage(Stage.ENRICH) if only_pending else store.all()
    if in_scope_only:
        profiles = [p for p in profiles if p.region.value in ("turkiye", "cee", "caucasus")]

    processed, errors = 0, 0
    with logger.stage(Stage.ENRICH.value, candidates=len(profiles), provider=provider.name):
        for p in profiles:
            try:
                store.upsert(_enrich_one(p, provider))
                processed += 1
                logger.log("enrich_ok", profile_id=p.id, confidence=p.overall_confidence)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                p.add_error(ProfileError(stage=Stage.ENRICH, code="enrich_failed",
                                         message=repr(exc)))
                store.upsert(p)
                logger.log("enrich_error", profile_id=p.id, error=repr(exc))
    elapsed = int((time.monotonic() - start) * 1000)
    status = stage_status(candidates=len(profiles), processed=processed, errors=errors)
    return ToolResult(status=status, stage=Stage.ENRICH,
                      data={"processed": processed, "errors": errors,
                            "provider": provider.name},
                      count=processed, run_id=logger.run_id, elapsed_ms=elapsed,
                      provenance=[provider.name],
                      message=f"enriched {processed} profiles ({errors} errors)")
