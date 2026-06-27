from __future__ import annotations

import json
import time
from pathlib import Path

from ..config import Config
from ..logging_utils import RunLogger
from ..schema import Profile, Stage, Status, ToolResult
from ..store import Store
from . import discover, enrich, export, extract, normalize, rank


def run_all(cfg: Config, store: Store, logger: RunLogger, target: int = 100,
            region: str = "all", max_discovery_rounds: int = 4) -> ToolResult[dict]:
    start = time.monotonic()
    steps: list[dict] = []

    def record(res: ToolResult) -> ToolResult:
        steps.append({"stage": res.stage.value, "status": res.status.value,
                      "count": res.count, "message": res.message})
        return res

    needed = target * 3
    for round_i in range(max_discovery_rounds):
        record(discover.run_discover(cfg, store, logger, region=region,
                                     limit=needed, max_queries=40 + round_i * 20))
        record(extract.run_extract(store, logger, cfg=cfg))
        record(normalize.run_normalize(store, logger))
        in_scope = sum(1 for p in store.all()
                       if p.region.value in ("turkiye", "cee", "caucasus"))
        logger.log("discovery_round", round=round_i, in_scope=in_scope, need=needed)
        if in_scope >= target:
            break

    record(enrich.run_enrich(cfg, store, logger))
    record(rank.run_rank(store, logger))
    exp = record(export.run_export(cfg, store, logger, target=target))

    elapsed = int((time.monotonic() - start) * 1000)
    status = Status.OK if exp.count >= target else Status.PARTIAL
    return ToolResult(status=status, stage=Stage.EXPORT,
                      data={"steps": steps, "exported": exp.count, "target": target,
                            "export_paths": exp.data},
                      count=exp.count, run_id=logger.run_id, elapsed_ms=elapsed,
                      message=f"pipeline complete: {exp.count}/{target} founders")


def validate_export(path: Path, target: int = 100,
                    min_confidence: float = 0.35) -> ToolResult[dict]:
    if not path.exists():
        return ToolResult.error(Stage.EXPORT, f"export not found: {path}")

    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return ToolResult.error(Stage.EXPORT, f"invalid json: {exc!r}")

    issues: list[str] = []
    valid = 0
    out_of_scope = 0
    low_conf = 0
    missing_name = 0
    non_founder = 0
    for rec in records:
        try:
            p = Profile.model_validate(rec)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"schema: {exc!r}")
            continue
        valid += 1
        if p.region.value not in ("turkiye", "cee", "caucasus"):
            out_of_scope += 1
        if p.overall_confidence < min_confidence:
            low_conf += 1
        if not p.full_name.value:
            missing_name += 1
        if p.is_founder.value is not True:
            non_founder += 1

    founder_ratio = (valid - non_founder) / valid if valid else 0.0
    checks = {
        "count_ok": len(records) >= target,
        "all_valid_schema": valid == len(records),
        "all_in_scope": out_of_scope == 0,
        "all_named": missing_name == 0,
        "all_confident": low_conf == 0,
        "mostly_founders": founder_ratio >= 0.85,
    }
    status = Status.OK if all(checks.values()) else Status.PARTIAL
    return ToolResult(status=status, stage=Stage.EXPORT,
                      data={"total": len(records), "valid": valid,
                            "out_of_scope": out_of_scope, "low_confidence": low_conf,
                            "missing_name": missing_name, "non_founder": non_founder,
                            "founder_ratio": round(founder_ratio, 3),
                            "checks": checks, "issues": issues[:10]},
                      count=valid,
                      message=f"validated {valid}/{len(records)} records")
