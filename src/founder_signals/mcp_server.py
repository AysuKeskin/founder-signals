from __future__ import annotations

from pathlib import Path
from typing import Optional

from .context import make_context
from .pipeline import (
    discover, enrich, export, extract, graph, history, normalize, rank, runner,
)

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    raise SystemExit("The 'mcp' package is required to run the MCP server.") from exc

mcp = FastMCP("founder-signals")


def _ctx():
    return make_context(echo=False)


@mcp.tool()
def discover_founders(region: str = "all", limit: int = 300, max_queries: int = 40) -> dict:
    """Discover founder candidates (region: turkiye|cee|caucasus|all)."""
    cfg, logger, store = _ctx()
    return discover.run_discover(cfg, store, logger, region=region,
                                 limit=limit, max_queries=max_queries).model_dump()


@mcp.tool()
def extract_profiles(reprocess_all: bool = False) -> dict:
    """Parse raw snippets into structured fields."""
    cfg, logger, store = _ctx()
    return extract.run_extract(store, logger, only_pending=not reprocess_all, cfg=cfg).model_dump()


@mcp.tool()
def normalize_profiles(reprocess_all: bool = False) -> dict:
    """Normalize fields and resolve region for stored profiles."""
    _cfg, logger, store = _ctx()
    return normalize.run_normalize(store, logger, only_pending=not reprocess_all).model_dump()


@mcp.tool()
def enrich_profiles(reprocess_all: bool = False) -> dict:
    """Enrich in-scope profiles with public context."""
    cfg, logger, store = _ctx()
    return enrich.run_enrich(cfg, store, logger, only_pending=not reprocess_all).model_dump()


@mcp.tool()
def rank_profiles() -> dict:
    """Score all profiles for export."""
    _cfg, logger, store = _ctx()
    return rank.run_rank(store, logger).model_dump()


@mcp.tool()
def export_founders(target: int = 100, min_confidence: Optional[float] = None) -> dict:
    """Export the top-N qualified founders to JSON + CSV."""
    cfg, logger, store = _ctx()
    return export.run_export(cfg, store, logger, target=target,
                             min_confidence=min_confidence).model_dump()


@mcp.tool()
def run_pipeline(target: int = 100, region: str = "all") -> dict:
    """Run the full discover->export pipeline and produce the founders export."""
    cfg, logger, store = _ctx()
    return runner.run_all(cfg, store, logger, target=target, region=region).model_dump()


@mcp.tool()
def validate_export(path: Optional[str] = None, target: int = 100) -> dict:
    """Validate an export file against schema + quality rules."""
    cfg, _logger, _store = _ctx()
    p = Path(path) if path else cfg.exports_dir / "founders.json"
    return runner.validate_export(p, target=target,
                                  min_confidence=cfg.min_confidence_export).model_dump()


@mcp.tool()
def inspect_profile(profile_id: str) -> dict:
    """Return a single stored profile with full provenance."""
    _cfg, _logger, store = _ctx()
    p = store.get(profile_id)
    return p.model_dump() if p else {"error": "not_found", "id": profile_id}


@mcp.tool()
def store_stats() -> dict:
    """Summary counts of the store by region and stage."""
    _cfg, _logger, store = _ctx()
    profiles = store.all()
    by_region: dict[str, int] = {}
    for p in profiles:
        key = p.region.value or "none"
        by_region[key] = by_region.get(key, 0) + 1
    return {"total": len(profiles), "by_region": by_region}


@mcp.tool()
def build_graph(top: Optional[int] = None) -> dict:
    """Build the founder↔company↔sector relationship graph (JSON + GraphML)."""
    _cfg, logger, store = _ctx()
    return graph.run_graph(store, logger, top=top).model_dump()


@mcp.tool()
def founder_connections(profile_id: str) -> dict:
    """Show who a founder is connected to (shared sector / company)."""
    _cfg, _logger, store = _ctx()
    return graph.connections(store, profile_id).model_dump()


@mcp.tool()
def diff_since_last_run(commit: bool = False) -> dict:
    """Founders new since the previous run; set commit=true to update the baseline."""
    cfg, logger, _store = _ctx()
    return history.run_diff(cfg.exports_dir / "founders.json", cfg.history_dir,
                            logger, commit=commit).model_dump()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
