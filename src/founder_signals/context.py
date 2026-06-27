from __future__ import annotations

from .config import Config, load_config
from .logging_utils import RunLogger, make_logger
from .store import Store


def make_context(echo: bool = True) -> tuple[Config, RunLogger, Store]:
    cfg = load_config()
    logger = make_logger(cfg.runs_dir, echo=echo)
    store = Store(cfg.store_path)
    return cfg, logger, store
