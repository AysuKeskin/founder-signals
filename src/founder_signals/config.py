from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _PKG_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _load_dotenv() -> None:
    for candidate in (Path.cwd() / ".env", PROJECT_ROOT / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
        break


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Config:
    source_mode: str = field(default_factory=lambda: _env("FS_SOURCE", "auto"))

    enrichment_mode: str = field(default_factory=lambda: _env("FS_ENRICH", "auto"))

    data_dir: Path = field(default_factory=lambda: Path(_env("FS_DATA_DIR", str(DATA_DIR))))

    request_timeout_s: float = field(default_factory=lambda: _env_float("FS_TIMEOUT", 12.0))
    rate_limit_s: float = field(default_factory=lambda: _env_float("FS_RATE_LIMIT", 1.2))
    max_retries: int = field(default_factory=lambda: _env_int("FS_MAX_RETRIES", 3))
    user_agent: str = field(
        default_factory=lambda: _env(
            "FS_USER_AGENT",
            "founder-signals-research/0.1 (+contact: case@bek.vc)",
        )
    )

    results_per_query: int = field(default_factory=lambda: _env_int("FS_RESULTS_PER_QUERY", 15))

    min_confidence_export: float = field(
        default_factory=lambda: _env_float("FS_MIN_CONFIDENCE", 0.35)
    )

    extract_mode: str = field(default_factory=lambda: _env("FS_EXTRACT", "auto"))
    llm_api_key: str = field(default_factory=lambda: _env("FS_LLM_API_KEY", ""))
    llm_base_url: str = field(
        default_factory=lambda: _env("FS_LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_model: str = field(default_factory=lambda: _env("FS_LLM_MODEL", "gpt-4o-mini"))
    llm_workers: int = field(default_factory=lambda: _env_int("FS_LLM_WORKERS", 6))
    llm_rpm: int = field(default_factory=lambda: _env_int("FS_LLM_RPM", 60))

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def store_path(self) -> Path:
        return self.data_dir / "store.sqlite"

    @property
    def history_dir(self) -> Path:
        return self.data_dir / "history"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.cache_dir, self.runs_dir,
                  self.exports_dir, self.history_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    _load_dotenv()
    cfg = Config()
    cfg.ensure_dirs()
    return cfg
