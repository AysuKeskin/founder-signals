from __future__ import annotations

import re
import time

from ..logging_utils import RunLogger
from ..regions import Region, region_from_linkedin_url, resolve_region
from ..schema import FieldValue, Profile, Stage, ToolResult, stage_status
from ..store import Store

_FOUNDER_TOKENS = (
    "founder", "co-founder", "co founder", "cofounder", "founding",
    "kurucu",
    "kurucu ortak",
    "owner", "co-owner",
    "girişimci", "girisimci", "entrepreneur",
)

_OWN_STARTUP_RE = re.compile(r"\bstartup\s*$", re.I)


def _is_founder(p: Profile) -> bool:
    # Use the person's title area only; full snippets may contain other profiles.
    parts = [p.headline.value, p.current_role.value]
    if p.raw_snippet:
        first = re.split(r"\.{2,}|…", p.raw_snippet)[0]
        parts.append(first.split("|")[0])
    text = " ".join(str(x) for x in parts if x).lower()
    if any(tok in text for tok in _FOUNDER_TOKENS):
        return True
    # "Stealth FinTech Startup" can be a founder signal even without "founder".
    title = (p.headline.value or "").split(" - ", 1)[-1].strip()
    return bool(_OWN_STARTUP_RE.search(title))


def _rollup_confidence(p: Profile) -> float:
    vals = [fv.confidence for _, fv in p.field_items() if fv.value is not None]
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def _normalize_one(p: Profile) -> Profile:
    loc = p.location_raw.value if p.location_raw.value else None
    cc_country, cc_region = region_from_linkedin_url(p.linkedin_url)

    if cc_region != Region.UNKNOWN:
        # LinkedIn country subdomains are usually a stronger region signal than text.
        city, _c, _r = resolve_region(loc)
        country, region = cc_country, cc_region
        region_source, region_conf = "linkedin_cc", 0.6
    else:
        city, country, region = resolve_region(loc)
        region_source, region_conf = "normalize", 0.7

    p.city = FieldValue(value=city, source="normalize",
                        confidence=0.6 if city else 0.0)
    p.country = FieldValue(value=country, source="normalize",
                           confidence=0.6 if country else 0.0)
    p.region = FieldValue(value=region.value, source=region_source,
                          confidence=region_conf if region.value != "unknown" else 0.2)

    founder = _is_founder(p)
    p.is_founder = FieldValue(value=founder, source="normalize",
                              confidence=0.7 if founder else 0.4)

    p.overall_confidence = _rollup_confidence(p)
    p.mark_stage(Stage.NORMALIZE)
    return p


def run_normalize(store: Store, logger: RunLogger,
                  only_pending: bool = True) -> ToolResult[dict]:
    start = time.monotonic()
    profiles = store.needing_stage(Stage.NORMALIZE) if only_pending else store.all()
    processed = 0
    region_counts: dict[str, int] = {}
    with logger.stage(Stage.NORMALIZE.value, candidates=len(profiles)):
        for p in profiles:
            p = _normalize_one(p)
            reg = p.region.value or "unknown"
            region_counts[reg] = region_counts.get(reg, 0) + 1
            store.upsert(p)
            processed += 1
    elapsed = int((time.monotonic() - start) * 1000)
    status = stage_status(candidates=len(profiles), processed=processed, errors=0)
    return ToolResult(status=status, stage=Stage.NORMALIZE,
                      data={"processed": processed, "by_region": region_counts},
                      count=processed, run_id=logger.run_id, elapsed_ms=elapsed,
                      message=f"normalized {processed} profiles")
