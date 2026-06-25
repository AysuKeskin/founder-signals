# Bek Founders

A CLI and MCP server for finding, normalizing, enriching, ranking, and exporting
startup founders from Turkiye, CEE, and the Caucasus.

The main output is:

- `data/exports/founders.json`
- `data/exports/founders.csv`

Design notes are in [DESIGN.md](./DESIGN.md).

## Data Scope

This project does not log in to LinkedIn and does not scrape LinkedIn pages.
Discovery uses public search snippets through DuckDuckGo:

- `site:linkedin.com/in` queries
- accelerator and portfolio-domain searches
- public web snippets for sector, stage, and link signals

If richer LinkedIn profile data is needed, add a provider behind
`EnrichmentProvider`. A placeholder already exists in
[sources/linkedin_provider.py](src/bek_founders/sources/linkedin_provider.py).

## Install

```bash
cd bek-founders
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quickstart

Run with the offline fixture:

```bash
BEK_SOURCE=mock bek run --target 100
BEK_SOURCE=mock bek validate
```

Outputs:

- `data/exports/founders.json` full records with confidence and provenance
- `data/exports/founders.csv` table-friendly export

Refresh the fixture from live public search:

```bash
python scripts/capture_seeds.py 100 360 8
```

## Live Mode

```bash
BEK_SOURCE=live bek run --target 100
```

The default is `BEK_SOURCE=auto`. If live search returns no usable results, the
pipeline falls back to the mock fixture.

## Commands

| Command | Purpose |
|---|---|
| `bek discover --region all --limit 300` | find candidate profiles |
| `bek extract` | parse raw snippets into fields |
| `bek normalize` | resolve location, founder flag, and confidence |
| `bek enrich` | add sector, stage, and link signals |
| `bek rank` | score profiles |
| `bek export --target 100` | write JSON and CSV exports |
| `bek run --target 100` | run the whole pipeline |
| `bek graph` | export founder-company-sector graph files |
| `bek connections <id>` | show shared sector/company connections |
| `bek diff [--commit]` | show new and dropped founders vs the last snapshot |
| `bek validate [path]` | validate an export |
| `bek inspect <id>` | show one profile in detail |
| `bek stats` | show store counts |
| `bek reset --yes` | clear the SQLite store |

Stages are idempotent. By default they process pending profiles only. Commands
that support reprocessing accept `--all`.

## Docker

```bash
docker build -t bek-founders .

docker compose run --rm cli run --target 100
docker compose run --rm cli validate

docker compose run --rm capture 100

docker run --rm --entrypoint sh bek-founders -c "pip install -q pytest && pytest -q"
```

MCP server:

```bash
docker run --rm -i bek-founders python -m bek_founders.mcp_server
```

## MCP Server

```bash
python -m bek_founders.mcp_server
mcp dev src/bek_founders/mcp_server.py
```

Example client config:

```json
{
  "mcpServers": {
    "bek-founders": {
      "command": "/abs/path/bek-founders/.venv/bin/python",
      "args": ["-m", "bek_founders.mcp_server"],
      "env": { "BEK_SOURCE": "auto" }
    }
  }
}
```

Tools:

`discover_founders`, `extract_profiles`, `normalize_profiles`, `enrich_profiles`,
`rank_profiles`, `export_founders`, `run_pipeline`, `build_graph`,
`founder_connections`, `diff_since_last_run`, `validate_export`,
`inspect_profile`, `store_stats`.

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `BEK_SOURCE` | `auto` | `auto` \| `live` \| `mock` |
| `BEK_ENRICH` | `auto` | `auto` \| `web` \| `mock` \| `linkedin` |
| `BEK_LINKEDIN_API_KEY` | - | API key for the LinkedIn provider |
| `BEK_DATA_DIR` | `./data` | store, cache, logs, exports |
| `BEK_MIN_CONFIDENCE` | `0.35` | export confidence threshold |
| `BEK_RATE_LIMIT` | `1.2` | delay between live requests |
| `BEK_MAX_RETRIES` | `3` | retry count for live sources |

## Tests

```bash
.venv/bin/python -m pytest
```

Tests run offline with the mock source.

## Project Layout

```text
src/bek_founders/
  schema.py        # Profile, FieldValue, ToolResult
  regions.py       # location -> region
  store.py         # SQLite store
  config.py        # env config
  logging_utils.py # JSONL run logs
  sources/         # discovery/enrichment providers
  pipeline/        # discover, extract, normalize, enrich, rank, export
  cli.py           # Typer CLI
  mcp_server.py    # MCP server
```
