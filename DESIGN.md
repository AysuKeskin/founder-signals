# Design Notes

Author: Aysu Keskin

These notes explain the main design choices behind the project. The goal is not
only to collect profiles, but to produce data that can be rerun, checked,
exported, and inspected.

## Problem

The target output is a list of 100 startup founders from Turkiye, CEE, and the
Caucasus. Each record includes as much useful structure as the public sources can
support: name, LinkedIn URL, company, location, sector, stage, confidence, and
source metadata.

Pipeline:

```text
discover -> extract -> normalize -> enrich -> rank -> export
```

SQLite sits between stages. This keeps runs resumable and dedupes repeated
profiles by a stable id.

## Data Sources

I did not log in to LinkedIn or scrape LinkedIn HTML. The live path uses:

- DuckDuckGo public search snippets
- `site:linkedin.com/in` queries
- accelerator and startup directory domains
- public web snippets for enrichment

This is less complete than a paid data provider, but it is simple to run, does
not require credentials, and is easy to test.

For richer profile data, the project has an `EnrichmentProvider` interface. A
commercial people-data provider (e.g. People Data Labs or Coresignal) could be
added behind it without changing the rest of the pipeline. (Note: Proxycurl, a
common LinkedIn data API, shut down in 2025 after LinkedIn legal action — a
reminder that scraping-based providers are fragile, which is why this project
reads search snippets instead.)

## Offline Fixture

`founder-signals capture` creates the seed file from live public search:

```text
src/founder_signals/sources/fixtures/founders_seed.json
```

The cached source replays this file, so the **input data is identical every run**
and works with no network. The whole run is fully deterministic with `regex`
extraction (what the tests use). `auto`/`llm` replay the same data but add small
run-to-run variation from the model. If the fixture is missing, the cached source
has a synthetic fallback.

## Schema

Main models:

- `Profile`: a founder candidate
- `FieldValue`: value, source, and confidence
- `ToolResult`: stage result

Confidence is stored per field, not only per profile, because some fields are
stronger than others.

## Extraction: regex vs LLM

Turning a messy LinkedIn search snippet into structured fields (company, role,
city, sectors, company_stage) is the brittle part. Three backends, chosen by
`FS_EXTRACT`:

- **`regex`:** rules in `pipeline/extract.py` that read LinkedIn's labelled fields
  when present (`Deneyim:`/Experience, `Konum:`/Location) and fall back to headline
  patterns, with blocklists for hobbies, job-titles, locations and name-slugs.
  Free, offline, deterministic — but still brittle: each new snippet shape can
  need another rule, and the rules are tuned to the data we have. Company filled
  ~88/100.
- **`llm`:** `sources/llm_extract.py` sends every snippet to a small LLM and asks
  for the fields as JSON. Handles varied, messy text far better than regex.
  Company ~99/100, but ~100 calls.
- **`auto` (default):** run regex first, then call the LLM only for the profiles
  it left thin (company / role / sectors empty). Same quality as full `llm`
  (~99/100 company) at a fraction of the calls, so it is the practical default.

The LLM uses the **OpenAI-compatible** API, so OpenAI, DeepSeek, or any compatible
endpoint work by changing `FS_LLM_BASE_URL`/`FS_LLM_MODEL`. Cheap models
(gpt-4o-mini, deepseek-chat) are plenty (~1–2 cents per 100). Calls are paced by
`FS_LLM_RPM` and run concurrently; on any error or missing key the pipeline
silently falls back to regex, so it never depends on the model being reachable.
Capture always uses regex (it only needs founder/region/dedupe decisions); the
LLM belongs in `run`, which re-extracts the fixture.

## Normalize and Rank

Region resolution checks:

1. LinkedIn country subdomains, when present
2. explicit country names in the location text
3. known city -> country mapping
4. `other` or `unknown` when unresolved

Founder detection checks English and Turkish terms (founder, co-founder, owner,
kurucu, kurucu ortak, girişimci, entrepreneur) plus headlines that *are* a venture
("... Stealth FinTech Startup"). It reads only the person's title (headline), not
the snippet body, to avoid attributing another glued-in profile's role.

Ranking differentiates *among* in-scope founders (out-of-scope scores `0.0`).
Founder + an earlier stage are favoured — the case is about spotting people
**early**, so pre-seed/seed/stealth outrank grown or exited companies:

- founder: `0.20`
- stage: `0.10` (earlier = higher; sparse, so a tie-breaker)
- has_company: `0.15`
- sectors: `0.15`
- completeness: `0.15`
- corroboration: `0.10`
- confidence: `0.15`

## Graph

`founder-signals graph` builds a small relationship graph from the exported founders:

```text
Founder -> Company
Founder -> Sector
Founder -> Region
```

Outputs:

- `data/exports/graph.json` — machine-readable node/edge list
- `data/exports/graph.graphml` — opens in Gephi / yEd
- `data/exports/graph.html` — self-contained interactive view (open in a browser)

`founder-signals connections <id>` shows founders connected through shared sectors or
companies.

## Diff

`founder-signals diff` compares the current export with the previous snapshot:

- new
- dropped
- retained count

Only one snapshot is kept:

```text
data/history/previous.json
```

`capture` saves the old fixture as the previous snapshot before writing a new
fixture, so replaying the fixture (a plain `run`) does not move the diff baseline.
If the snapshot is missing, the first diff is treated as the baseline and can be
saved locally with `founder-signals diff --commit`.

## Logging

Each run gets a `run_id` and writes structured **JSONL** logs to
`data/runs/<run_id>.jsonl`. Each line is one JSON object, so logs are easy to
inspect with `rg`/`jq` and parse programmatically. Stages emit `stage_start` and
`stage_end` with `elapsed_ms`; domain events include `discover_query`,
`enrich_ok`, `llm_overlay`, and `discover_fallback`:

```json
{"ts": 1782543826.35, "run_id": "run_959098dd", "event": "stage_start", "stage": "discover", "queries": 40}
{"ts": 1782543826.35, "run_id": "run_959098dd", "event": "discover_query", "source": "cached", "query": "...", "hits": 15}
{"ts": 1782543826.60, "run_id": "run_959098dd", "event": "stage_end", "stage": "extract", "elapsed_ms": 57}
```

A developer or reviewer can see what each stage did, how long it took, which
source answered, and whether the run fell back or hit errors. Logs are separate
from the command's `ToolResult`; they also stream to stderr unless `--quiet`,
keeping stdout reserved for the JSON result.

## Validation

`founder-signals validate` checks:

- target count
- JSON schema
- target region
- name presence
- confidence threshold
- founder ratio

## Limits

- Public search snippets do not contain full profile data.
- `company_stage` is sparse because funding/stage information is often not in a
  person's headline or snippet.
- Live search can hit DuckDuckGo rate limits. `auto` mode can fall back to the
  cached source.
- The city-country map covers major hubs and can be extended.

## Run

```bash
FS_SOURCE=cached founder-signals run --target 100
FS_SOURCE=cached founder-signals validate
```

Refresh live data, then re-run:

```bash
founder-signals capture --target 100
FS_SOURCE=cached founder-signals run --target 100
```
