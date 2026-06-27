from __future__ import annotations

import json
import time
from pathlib import Path

from ..logging_utils import RunLogger
from ..schema import Stage, Status, ToolResult

_SNAPSHOT = "previous.json"


def snapshot_fixture(fixture_path: Path, history_dir: Path) -> int:
    from ..store import profile_id  # local import avoids a cycle at module load
    try:
        seeds = json.loads(fixture_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    recs = [{"id": profile_id(s.get("url")), "name": s.get("name"),
             "url": s.get("url"), "region": s.get("region"), "rank_score": None}
            for s in seeds if s.get("url")]
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / _SNAPSHOT).write_text(
        json.dumps(recs, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(recs)


def _load_export(export_json: Path) -> list[dict]:
    try:
        return json.loads(export_json.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_snapshot(snapshot_path: Path) -> dict[str, dict]:
    try:
        recs = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return {r["id"]: r for r in recs}
    except Exception:
        return {}


def _record(rec: dict) -> dict:
    fv = lambda k: (rec.get(k) or {}).get("value")  # noqa: E731
    return {"id": rec.get("id"), "name": fv("full_name"),
            "url": rec.get("linkedin_url"), "region": fv("region"),
            "rank_score": rec.get("rank_score")}


def run_diff(export_json: Path, history_dir: Path, logger: RunLogger | None = None,
             commit: bool = False, out_dir: Path | None = None) -> ToolResult[dict]:
    start = time.monotonic()
    history_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = history_dir / _SNAPSHOT

    current_raw = _load_export(export_json)
    if not current_raw:
        return ToolResult.error(Stage.EXPORT, f"no export to diff: {export_json}")
    current = {r["id"]: _record(r) for r in current_raw if r.get("id")}
    previous = _load_snapshot(snapshot_path)

    new_ids = [i for i in current if i not in previous]
    dropped_ids = [i for i in previous if i not in current]
    retained_ids = [i for i in current if i in previous]

    baseline = not previous
    data = {
        "baseline": baseline,
        "current_count": len(current),
        "previous_count": len(previous),
        "new": [current[i] for i in new_ids],
        "dropped": [previous[i] for i in dropped_ids],
        "retained_count": len(retained_ids),
        "committed": False,
    }

    if commit:
        snapshot_path.write_text(
            json.dumps(list(current.values()), indent=2, ensure_ascii=False),
            encoding="utf-8")
        data["committed"] = True

    out_dir = out_dir or export_json.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = out_dir / "diff.json"
    diff_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    data["diff_file"] = str(diff_path)

    if logger:
        logger.log("diff", new=len(new_ids), dropped=len(dropped_ids),
                   retained=len(retained_ids), baseline=baseline, committed=commit)

    elapsed = int((time.monotonic() - start) * 1000)
    msg = ("baseline established" if baseline
           else f"{len(new_ids)} new, {len(dropped_ids)} dropped since last run")
    return ToolResult(status=Status.OK, stage=Stage.EXPORT, data=data,
                      count=len(new_ids), elapsed_ms=elapsed,
                      run_id=logger.run_id if logger else None,
                      message=msg + (" (committed)" if commit else ""))
