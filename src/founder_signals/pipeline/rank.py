from __future__ import annotations

import time

from ..logging_utils import RunLogger
from ..regions import Region, in_scope
from ..schema import Profile, Stage, Status, ToolResult
from ..store import Store

WEIGHTS = {
    # The score favors in-scope founders with early-stage signals and enough structure to verify.
    "founder": 0.20,
    "stage": 0.10,
    "has_company": 0.15,
    "sectors": 0.15,
    "completeness": 0.15,
    "corroboration": 0.10,
    "confidence": 0.15,
}

_STAGE_SCORE = {
    "pre-seed": 1.0, "seed": 0.9, "accelerator-backed": 0.85,
    "stealth": 0.7, "bootstrapped": 0.7, "funded": 0.6, "series a": 0.45,
    "series b": 0.3, "series c": 0.2, "series d+": 0.15, "acquired": 0.1, "ipo": 0.05,
}
_STAGE_UNKNOWN = 0.5


def score_profile(p: Profile) -> float:
    region_val = p.region.value or "unknown"
    try:
        region = Region(region_val)
    except ValueError:
        region = Region.UNKNOWN
    if not in_scope(region):
        return 0.0

    founder = 1.0 if (p.is_founder.value is True) else 0.0
    stage = _STAGE_SCORE.get(p.company_stage.value, _STAGE_UNKNOWN)
    has_company = 1.0 if p.current_company.value else 0.0
    has_sectors = 1.0 if (isinstance(p.sectors.value, list) and p.sectors.value) else 0.0

    fields = p.field_items()
    populated = sum(1 for _, fv in fields if fv.value not in (None, [], ""))
    completeness = min(populated / len(fields), 1.0)
    # Extra URLs are weak corroboration, capped so noisy profiles do not dominate.
    corroboration = min(len(set(p.source_urls)) / 3.0, 1.0)
    confidence = p.overall_confidence

    score = (
        WEIGHTS["founder"] * founder
        + WEIGHTS["stage"] * stage
        + WEIGHTS["has_company"] * has_company
        + WEIGHTS["sectors"] * has_sectors
        + WEIGHTS["completeness"] * completeness
        + WEIGHTS["corroboration"] * corroboration
        + WEIGHTS["confidence"] * confidence
    )
    return round(score, 4)


def run_rank(store: Store, logger: RunLogger) -> ToolResult[dict]:
    start = time.monotonic()
    profiles = store.all()
    in_scope_n = 0
    with logger.stage(Stage.RANK.value, candidates=len(profiles)):
        for p in profiles:
            p.rank_score = score_profile(p)
            if p.rank_score > 0:
                in_scope_n += 1
            p.mark_stage(Stage.RANK)
            store.upsert(p)
    elapsed = int((time.monotonic() - start) * 1000)
    top = store.ranked(limit=5)
    status = Status.OK if in_scope_n else Status.PARTIAL
    return ToolResult(status=status, stage=Stage.RANK,
                      data={"ranked": len(profiles), "in_scope": in_scope_n,
                            "weights": WEIGHTS,
                            "top_preview": [
                                {"id": t.id, "name": t.full_name.value,
                                 "score": t.rank_score} for t in top]},
                      count=in_scope_n, run_id=logger.run_id, elapsed_ms=elapsed,
                      message=f"ranked {len(profiles)} profiles, {in_scope_n} in scope")
