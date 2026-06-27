from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .context import make_context
from .pipeline import (
    discover, enrich, export, extract, graph, history, normalize, rank, runner,
)
from .schema import ToolResult

app = typer.Typer(
    add_completion=False,
    help="Discover, normalize, enrich & rank Türkiye/CEE/Caucasus startup founders.",
)


def _emit(result: ToolResult) -> None:
    typer.echo(json.dumps(result.model_dump(), default=str, ensure_ascii=False, indent=2))
    if result.status.value == "error":
        raise typer.Exit(code=1)


def _ctx(quiet: bool):
    return make_context(echo=not quiet)


@app.command("discover")
def discover_cmd(
    region: str = typer.Option("all", "--region", help="turkiye|cee|caucasus|all"),
    limit: int = typer.Option(300, help="max raw candidates to collect"),
    max_queries: int = typer.Option(40, help="max search queries to issue"),
    quiet: bool = typer.Option(False, help="suppress stderr logs"),
) -> None:
    """Discover founder candidates from public sources."""
    cfg, logger, store = _ctx(quiet)
    _emit(discover.run_discover(cfg, store, logger, region=region,
                                limit=limit, max_queries=max_queries))


@app.command("extract")
def extract_cmd(all_: bool = typer.Option(False, "--all", help="re-extract everything"),
                quiet: bool = typer.Option(False)) -> None:
    """Parse raw snippets into structured fields."""
    cfg, logger, store = _ctx(quiet)
    _emit(extract.run_extract(store, logger, only_pending=not all_, cfg=cfg))


@app.command("normalize")
def normalize_cmd(all_: bool = typer.Option(False, "--all"),
                  quiet: bool = typer.Option(False)) -> None:
    """Normalize fields & resolve region."""
    _cfg, logger, store = _ctx(quiet)
    _emit(normalize.run_normalize(store, logger, only_pending=not all_))


@app.command("enrich")
def enrich_cmd(all_: bool = typer.Option(False, "--all"),
               quiet: bool = typer.Option(False)) -> None:
    """Enrich in-scope profiles with public context."""
    cfg, logger, store = _ctx(quiet)
    _emit(enrich.run_enrich(cfg, store, logger, only_pending=not all_))


@app.command("rank")
def rank_cmd(quiet: bool = typer.Option(False)) -> None:
    """Score profiles for export."""
    _cfg, logger, store = _ctx(quiet)
    _emit(rank.run_rank(store, logger))


@app.command("export")
def export_cmd(target: int = typer.Option(100, help="number of founders to export"),
               min_confidence: Optional[float] = typer.Option(None),
               quiet: bool = typer.Option(False)) -> None:
    """Export the top-N qualified founders to JSON + CSV."""
    cfg, logger, store = _ctx(quiet)
    _emit(export.run_export(cfg, store, logger, target=target,
                            min_confidence=min_confidence))


@app.command()
def run(target: int = typer.Option(100, help="founders to produce"),
        region: str = typer.Option("all"),
        quiet: bool = typer.Option(False)) -> None:
    """Run the full pipeline end-to-end (discover -> export)."""
    cfg, logger, store = _ctx(quiet)
    _emit(runner.run_all(cfg, store, logger, target=target, region=region))


@app.command("capture")
def capture_cmd(target: int = typer.Option(100, help="founders to record"),
                max_seconds: int = typer.Option(360, help="discovery time budget"),
                workers: int = typer.Option(8, help="concurrent search workers")) -> None:
    """Refresh the fixture from public search."""
    from .capture import run_capture
    summary = run_capture(target=target, max_seconds=max_seconds, workers=workers)
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command("graph")
def graph_cmd(top: Optional[int] = typer.Option(None, help="limit to top-N ranked founders"),
              quiet: bool = typer.Option(False)) -> None:
    """Build the founder↔company↔sector relationship graph (JSON + GraphML)."""
    _cfg, logger, store = _ctx(quiet)
    _emit(graph.run_graph(store, logger, top=top))


@app.command("connections")
def connections_cmd(profile_id: str = typer.Argument(...),
                    quiet: bool = typer.Option(True)) -> None:
    """Show who a founder is connected to (shared sector / company)."""
    _cfg, _logger, store = _ctx(quiet)
    _emit(graph.connections(store, profile_id))


@app.command("diff")
def diff_cmd(commit: bool = typer.Option(False, "--commit",
                                         help="manually roll the baseline (normally done by capture)"),
             quiet: bool = typer.Option(False)) -> None:
    """Founders new since the last saved snapshot."""
    cfg, logger, _store = _ctx(quiet)
    _emit(history.run_diff(cfg.exports_dir / "founders.json", cfg.history_dir,
                           logger, commit=commit))


@app.command()
def validate(path: str = typer.Argument(None, help="export json (default: data/exports/founders.json)"),
             target: int = typer.Option(100),
             quiet: bool = typer.Option(True)) -> None:
    """Validate an export against the schema + quality rules."""
    cfg, _logger, _store = _ctx(quiet)
    p = Path(path) if path else cfg.exports_dir / "founders.json"
    _emit(runner.validate_export(p, target=target,
                                 min_confidence=cfg.min_confidence_export))


@app.command()
def inspect(profile_id: str = typer.Argument(...),
            quiet: bool = typer.Option(True)) -> None:
    """Show a single stored profile (full provenance) as JSON."""
    _cfg, _logger, store = _ctx(quiet)
    p = store.get(profile_id)
    if not p:
        typer.echo(json.dumps({"error": "not_found", "id": profile_id}))
        raise typer.Exit(code=1)
    typer.echo(json.dumps(p.model_dump(), default=str, ensure_ascii=False, indent=2))


@app.command()
def stats(quiet: bool = typer.Option(True)) -> None:
    """Summarize the store: counts by region and stage."""
    _cfg, _logger, store = _ctx(quiet)
    profiles = store.all()
    by_region: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    for p in profiles:
        by_region[p.region.value or "none"] = by_region.get(p.region.value or "none", 0) + 1
        for s in p.stages_done:
            by_stage[s.value] = by_stage.get(s.value, 0) + 1
    typer.echo(json.dumps(
        {"total": len(profiles), "by_region": by_region, "by_stage": by_stage},
        ensure_ascii=False, indent=2))


@app.command()
def reset(yes: bool = typer.Option(False, "--yes", help="confirm wipe")) -> None:
    """Clear the store (start a fresh run)."""
    cfg, _logger, store = _ctx(quiet=True)
    if not yes:
        typer.echo(json.dumps({"error": "pass --yes to confirm reset"}))
        raise typer.Exit(code=1)
    store.clear()
    typer.echo(json.dumps({"status": "ok", "message": "store cleared"}))


if __name__ == "__main__":
    app()
