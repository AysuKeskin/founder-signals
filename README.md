# Founder Signals

Founder Signals is a CLI and MCP server for finding, normalizing, enriching,
ranking, and exporting startup founders from Turkiye, CEE, and the Caucasus.

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
[sources/linkedin_provider.py](src/founder_signals/sources/linkedin_provider.py).

## How it works

There are **two separate steps** — `capture` (fetch raw data from the web) and
`run` (turn it into the final 100-founder export). You usually `run`; you only
`capture` when you want fresh data.

```
   founder-signals capture                founder-signals run
 ┌─────────────────────┐                ┌──────────────────────────────────┐
 │ fetch from web      │   writes the   │ discover → extract → normalize → │
 │ (DuckDuckGo)        │ ───fixture───▶ │ enrich → rank → export           │
 │ select 100 founders │  founders_     │                                  │
 │ (regex decisions)   │  seed.json     │ -> data/exports/founders.{json,csv}
 └─────────────────────┘                └──────────────────────────────────┘
        ~1-2 min                            ~1 s (regex) · ~50 s (auto/LLM)
     (network, occasional)               (replays the fixture; the usual command)
```

### `capture` — refresh the data (occasional)

`founder-signals capture` hits the public web (DuckDuckGo), finds founder
candidates, and selects the best 100 into a **fixture** —
`founder_signals/sources/fixtures/founders_seed.json`. It records the raw search
snippets so `run` can re-process them offline. Capture always uses **regex** for
its selection decisions (is-founder / region / dedupe) — it does not need an LLM
and has no extraction modes. It is the only thing that touches the network.

### `run` — produce the export (the usual command)

`founder-signals run` replays the fixture through the six-stage pipeline and
writes `data/exports/founders.{json,csv}`. The recorded data means it is offline
and fast — ~1 s with `FS_EXTRACT=regex` (fully deterministic), ~50 s with the
default `auto` (LLM) extraction, which replays the same data but adds small
run-to-run variation. Each stage is independently runnable and
resumable (state in a small SQLite store). Two extras sit on top: **`graph`**
(founder↔company↔sector relationships) and **`diff`** (what's new since last run).

### Data source: `FS_SOURCE`

Where discovery/enrichment get their data:

| `FS_SOURCE` | Meaning |
|---|---|
| `cached` | replay the recorded fixture — offline, no network, same data every run (tests + default demo) |
| `live` | query the public web now |
| `auto` | try live, fall back to cached |

### Extraction backend: `FS_EXTRACT` (only affects `run`)

How `run` turns each snippet into fields (company, role, city, sectors). Parsing
messy LinkedIn snippets is the brittle part, so there are three backends — the
default is **`auto`**:

| `FS_EXTRACT` | What it does | Company filled | Speed (100) | API key |
|---|---|---|---|---|
| **`auto` (default)** | regex first, then an LLM **fills only the gaps** | 99/100 | ~50 s | required* |
| `llm` | every profile goes through the LLM (highest quality) | 99/100 | ~100 s | required* |
| `regex` | rule-based only — no LLM, free, fully offline/deterministic | 88/100 | ~1 s | none |

\* `auto` and `llm` need an LLM API key. **Without a key they fall back to `regex`
automatically**, so the project always runs — the default demo and tests work
offline with zero setup.

In `auto`, a profile is sent to the LLM only when regex left **company, role, or
sectors** empty (the fields that matter for a founder record). Region is already
resolved for everyone, and city is treated as secondary — so we don't spend an
LLM call just to fill a city. When a profile does go to the LLM, the model fills
its empty fields (including city) **without overwriting what regex already found**.

For the **cleanest possible export**, use `llm`. `auto` trusts regex wherever it
produced a value; `llm` re-derives every field, so it also *improves* values that
regex filled but got weak or partial (e.g. a vague role). It costs ~2× the time
and calls of `auto` for a small bump (role 93→97, city 58→60 in our runs), so:
**use `auto` for day-to-day, and `llm` for a final, ship-quality export.**

**To enable the LLM** (for `auto`/`llm`), set these in `.env`:

```bash
FS_EXTRACT=auto                              # already the default
FS_LLM_API_KEY=sk-...                        # your key (see below)
FS_LLM_BASE_URL=https://api.openai.com/v1    # provider endpoint
FS_LLM_MODEL=gpt-4o-mini                      # model name
```

Where to get a key (any **OpenAI-compatible** provider works):

| Provider | `FS_LLM_BASE_URL` | `FS_LLM_MODEL` | Get a key at |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | platform.openai.com → API keys |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | platform.deepseek.com |

Cheap models like these are plenty for this task (~1-2 cents per 100 founders).
If you hit rate limits (429), lower `FS_LLM_RPM`. Full LLM settings are in
[Configuration](#configuration).

Every stage returns a uniform `ToolResult` (`status`, `data`, `errors`,
`provenance`, `confidence`), and each exported field keeps its own source and
confidence — so you can see whether a value came from `extract`, `extract:llm`,
or enrichment.

Each run also writes structured **JSONL logs** to `data/runs/<run_id>.jsonl`.
Each line is one JSON event, including `stage_start`, `stage_end`,
`discover_query`, `enrich_ok`, fallbacks, and errors. This makes it easy to see
what each stage did and how long it took:

```bash
cat "data/runs/$(ls -t data/runs | head -1)"
```

## Quickstart (Docker)

No local Python needed. The image pins every dependency, so it runs the same
anywhere. `data/` is bind-mounted, so exports land on the host.

```bash
docker build -t founder-signals .
docker compose run --rm cli run --target 100          # fixture -> export
docker compose run --rm cli validate                  # quality-gate the export
docker compose run --rm capture --target 100          # refresh fixture, then `run` again
docker run --rm --entrypoint sh founder-signals -c "pip install -q pytest && pytest -q"
```

Outputs:

- `data/exports/founders.json` full records with confidence and provenance
- `data/exports/founders.csv` table-friendly export

To run many commands without the `docker compose run` prefix each time, open a
shell in the container once:

```bash
docker run --rm -it --entrypoint sh -v "$(pwd)/data:/app/data" founder-signals
founder-signals discover --region all --limit 300
founder-signals run --target 100
```

## Example output

`founders.csv` — flat, analyst-friendly (one row per founder). Selected columns
shown; the file also has `headline`, `current_role`, `city`, `country`,
`company_stage`, `source_urls`, `n_errors`:

```csv
rank,full_name,region,current_company,sectors,linkedin_url,overall_confidence,rank_score
1,Tarık Demir,turkiye,Lisa AI,AI/ML,https://tr.linkedin.com/in/demirtarik,0.65,0.9086
2,Zeki Ünyıldız,turkiye,Fundeep,AI/ML,https://tr.linkedin.com/in/zekiunyildiz,0.661,0.8866
```

`founders.json` — full records where each field keeps its source and confidence:

```json
{
  "id": "p_cf5d0b4cb0c6294e",
  "full_name":       { "value": "Tarık Demir", "source": "cached",
                        "source_url": "https://tr.linkedin.com/in/demirtarik", "confidence": 0.6 },
  "current_company": { "value": "Lisa AI", "source": "extract:llm", "confidence": 0.8 },
  "region":          { "value": "turkiye", "source": "linkedin_cc", "confidence": 0.6 },
  "sectors":         { "value": ["AI/ML"], "source": "cached", "confidence": 0.7 },
  "overall_confidence": 0.65,
  "rank_score": 0.9086
}
```

## Local install (for development)

Prefer Docker for a clean run; use a local venv for fast iteration.

```bash
cd founder-signals
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"          # uses pyproject.toml
pip install -r requirements.txt
```

Then run the pipeline against the offline fixture:

```bash
FS_SOURCE=cached founder-signals run --target 100
FS_SOURCE=cached founder-signals validate
```

Refreshing the data is **two steps**: `capture` updates the recorded fixture;
`run` then processes it into the export. Capture does not write
`founders.csv/json` itself — it only updates `founders_seed.json`.

```bash
founder-signals capture --target 100        # 1. fetch live -> founder_signals/sources/fixtures/
FS_SOURCE=cached founder-signals run         # 2. process fixture -> data/exports/
```

(`capture` also rolls the diff baseline forward, so the next `founder-signals diff`
shows who is new since this capture.)

## Live Mode

```bash
FS_SOURCE=live founder-signals run --target 100
```

The default is `FS_SOURCE=auto`. If live search returns no usable results, the
pipeline falls back to the cached fixture.

## Commands

> Prefix with `FS_SOURCE=cached` to run offline against the recorded fixture
> (no network). Without it the default `FS_SOURCE=auto` may hit the live web for
> discovery.

**Main commands** — the two you actually use day to day:

| Command | Purpose |
|---|---|
| `founder-signals run --target 100` | run the whole pipeline (fixture -> export) — **the usual command** |
| `founder-signals capture --target 100` | fetch a fresh fixture from the web (data refresh; then `run`) |

**Pipeline stages** — the six stages `run` chains; runnable individually for
debugging or reprocessing:

| Command | Purpose |
|---|---|
| `founder-signals discover --region all --limit 300` | find candidate profiles |
| `founder-signals extract` | parse raw snippets into fields |
| `founder-signals normalize` | resolve location, founder flag, and confidence |
| `founder-signals enrich` | add sector, stage, and link signals |
| `founder-signals rank` | score profiles |
| `founder-signals export --target 100` | write JSON and CSV exports |

**Analysis & utilities:**

| Command | Purpose |
|---|---|
| `founder-signals graph` | export the relationship graph (`graph.json`, `graph.graphml`, `graph.html`) |
| `founder-signals connections <id>` | show shared sector/company connections |
| `founder-signals diff [--commit]` | new/dropped founders vs the last snapshot (writes `diff.json`) |
| `founder-signals validate [path]` | validate an export |
| `founder-signals inspect <id>` | show one profile in detail |
| `founder-signals stats` | show store counts |
| `founder-signals reset --yes` | clear the SQLite store |

If no local snapshot exists yet, `diff` treats the current export as the first
baseline; use `founder-signals diff --commit` to save that baseline locally.

Stages are idempotent. By default they process pending profiles only. Commands
that support reprocessing accept `--all`.

## MCP Server

Run over stdio, locally or in Docker:

```bash
python -m founder_signals.mcp_server                       # local venv
docker run --rm -i founder-signals python -m founder_signals.mcp_server   # Docker
mcp dev src/founder_signals/mcp_server.py                  # MCP Inspector
```

Example client config:

```json
{
  "mcpServers": {
    "founder-signals": {
      "command": "/abs/path/founder-signals/.venv/bin/python",
      "args": ["-m", "founder_signals.mcp_server"],
      "env": { "FS_SOURCE": "auto" }
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

Copy `.env.example` to `.env` and edit — the CLI loads it automatically
(`cp .env.example .env`). Variables already exported in your shell take
precedence. For Docker: `docker compose --env-file .env run ...`.

| Var | Default | Meaning |
|---|---|---|
| `FS_SOURCE` | `auto` | `auto` \| `live` \| `cached` |
| `FS_ENRICH` | `auto` | `auto` \| `web` \| `cached` \| `linkedin` |
| `FS_LINKEDIN_API_KEY` | - | API key for the LinkedIn provider |
| `FS_DATA_DIR` | `./data` | store, cache, logs, exports |
| `FS_MIN_CONFIDENCE` | `0.35` | export confidence threshold |
| `FS_RATE_LIMIT` | `1.2` | delay between live requests |
| `FS_MAX_RETRIES` | `3` | retry count for live sources |
| `FS_TIMEOUT` | `12.0` | per-request timeout (seconds) |
| `FS_RESULTS_PER_QUERY` | `15` | search results fetched per query |
| `FS_USER_AGENT` | `founder-signals-research/0.1` | HTTP User-Agent for live requests |

### LLM extraction (used by `run`)

| Var | Default | Meaning |
|---|---|---|
| `FS_EXTRACT` | `auto` | `auto` \| `llm` \| `regex` (see [How it works](#extraction-backend-fs_extract-only-affects-run)) |
| `FS_LLM_API_KEY` | - | OpenAI-compatible API key (OpenAI / DeepSeek / …); without it, falls back to `regex` |
| `FS_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI: `…/v1` · DeepSeek: `https://api.deepseek.com` |
| `FS_LLM_MODEL` | `gpt-4o-mini` | OpenAI: `gpt-4o-mini` · DeepSeek: `deepseek-chat` |
| `FS_LLM_RPM` | `60` | requests/minute cap — lower if you hit 429s, raise to go faster |
| `FS_LLM_WORKERS` | `6` | parallel LLM calls (paced by `FS_LLM_RPM`) |

The default is `auto`; add `FS_LLM_API_KEY` and run
`founder-signals run`. Without a key it silently stays on `regex`.

## Tests

```bash
.venv/bin/python -m pytest
```

Tests run offline with the cached source.

## Project Layout

```text
src/founder_signals/
  schema.py        # Profile, FieldValue, ToolResult
  regions.py       # location -> region
  store.py         # SQLite store
  config.py        # env config
  context.py       # shared config/store/logger setup for CLI + MCP
  logging_utils.py # JSONL run logs
  capture.py       # refresh the fixture from public search
  sources/         # discovery/enrichment providers + LLM extraction
  pipeline/        # discover, extract, normalize, enrich, rank, export, graph, diff
  cli.py           # Typer CLI
  mcp_server.py    # MCP server
```
