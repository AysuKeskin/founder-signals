from __future__ import annotations

import sys

from founder_signals.capture import run_capture

if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    max_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 360
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    run_capture(target=target, max_seconds=max_seconds, workers=workers)
