from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from ..config import Config
from ..logging_utils import RunLogger
from ..schema import Profile, Stage, Status, ToolResult
from ..store import Store

_CSV_FIELDS = [
    "rank", "id", "full_name", "headline", "is_founder", "current_role",
    "current_company", "city", "country", "region", "sectors", "company_stage",
    "linkedin_url", "overall_confidence", "rank_score", "source_urls", "n_errors",
]


def _flat_row(rank: int, p: Profile) -> dict:
    def v(fv):
        val = fv.value
        return ", ".join(map(str, val)) if isinstance(val, list) else val
    return {
        "rank": rank,
        "id": p.id,
        "full_name": v(p.full_name),
        "headline": v(p.headline),
        "is_founder": v(p.is_founder),
        "current_role": v(p.current_role),
        "current_company": v(p.current_company),
        "city": v(p.city),
        "country": v(p.country),
        "region": v(p.region),
        "sectors": v(p.sectors),
        "company_stage": v(p.company_stage),
        "linkedin_url": p.linkedin_url,
        "overall_confidence": p.overall_confidence,
        "rank_score": p.rank_score,
        "source_urls": "; ".join(p.source_urls),
        "n_errors": len(p.errors),
    }


def run_export(cfg: Config, store: Store, logger: RunLogger,
               target: int = 100, min_confidence: float | None = None,
               out_dir: Path | None = None) -> ToolResult[dict]:
    start = time.monotonic()
    min_conf = cfg.min_confidence_export if min_confidence is None else min_confidence
    out_dir = out_dir or cfg.exports_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    qualified = [
        p for p in store.ranked()
        if (p.rank_score or 0) > 0 and p.overall_confidence >= min_conf
    ][:target]

    json_path = out_dir / "founders.json"
    csv_path = out_dir / "founders.csv"

    with logger.stage(Stage.EXPORT.value, qualified=len(qualified), target=target):
        json_path.write_text(
            json.dumps([p.model_dump() for p in qualified], indent=2, default=str),
            encoding="utf-8",
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for i, p in enumerate(qualified, 1):
                writer.writerow(_flat_row(i, p))

    elapsed = int((time.monotonic() - start) * 1000)
    shortfall = max(0, target - len(qualified))
    status = Status.OK if len(qualified) >= target else Status.PARTIAL
    return ToolResult(status=status, stage=Stage.EXPORT,
                      data={"exported": len(qualified), "target": target,
                            "shortfall": shortfall,
                            "json": str(json_path), "csv": str(csv_path)},
                      count=len(qualified), run_id=logger.run_id, elapsed_ms=elapsed,
                      message=f"exported {len(qualified)}/{target} founders to {out_dir}")
