from __future__ import annotations

import json
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


class RunLogger:
    def __init__(self, run_id: str, runs_dir: Path, echo: bool = True):
        self.run_id = run_id
        self.echo = echo
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.path = runs_dir / f"{run_id}.jsonl"

    def log(self, event: str, **fields: Any) -> None:
        record = {"ts": time.time(), "run_id": self.run_id, "event": event, **fields}
        line = json.dumps(record, default=str, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if self.echo:
            print(line, file=sys.stderr)

    @contextmanager
    def stage(self, stage: str, **fields: Any) -> Iterator[None]:
        start = time.monotonic()
        self.log("stage_start", stage=stage, **fields)
        try:
            yield
        except Exception as exc:  # noqa: BLE001 - we re-raise after logging
            self.log("stage_error", stage=stage, error=repr(exc))
            raise
        finally:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self.log("stage_end", stage=stage, elapsed_ms=elapsed_ms)


def make_logger(runs_dir: Path, run_id: Optional[str] = None, echo: bool = True) -> RunLogger:
    return RunLogger(run_id or new_run_id(), runs_dir, echo=echo)
