# River Chemistry Anomaly Engine

A four-layer pipeline that turns raw Environment Agency freshwater monitoring data
into a ranked anomaly feed with plain-English site summaries.

## Architecture

```text
EA Open Data
  |
  v
01_ingest       Pull and parse EA bulk/API data
  |
  v
02_fingerprint 12-feature signature and UMAP embedding per site
  |
  v
03_score       Anomaly scoring and national ranking
  |
  v
04_narrate     Plain-English summaries per flagged site
  |
  v
data/output/ranked_feed.json
```

## Quick Start

```bash
# Run the full pipeline
python src/run_pipeline.py

# Or run each layer independently
python src/01_ingest.py
python src/02_fingerprint.py
python src/03_score.py
python src/04_narrate.py
```

## Frontend Data

`data/output/ranked_feed.json` is the pipeline source of truth and should be
tracked because the public frontend depends on it. For frontend builds, copy that
file to `frontend/public/data/ranked_feed.json`, which is the static copy served
by Vite and included in the deployed app.

### Pipeline Architecture

The pipeline converts research notebook code into production modules:

| Processing Step                        | Module                  |
|----------------------------------------|-------------------------|
| EA data download / API calls           | `src/01_ingest.py`      |
| Column renaming, filtering, cleaning   | `src/01_ingest.py`      |
| Left-censored value parsing (`<x→x/2`) | `src/01_ingest.py`      |
| Determinand exclusions, unit filtering | `src/01_ingest.py`      |
| 12-feature panel construction          | `src/02_fingerprint.py` |
| Site-level aggregation (median/mean)   | `src/02_fingerprint.py` |
| UMAP fitting + embedding               | `src/02_fingerprint.py` |
| WFD typology joining                   | `src/02_fingerprint.py` |

### Development Process

The pipeline architecture, scoring logic, and narration templates were designed
and validated by the author. Implementation was accelerated using AI coding
assistants (Claude, ChatGPT). All outputs are verified through a three-gate
quality assurance process (data sanity, ranking quality, output quality) with
manual review before each release.

The research methodology, statistical approach, and domain interpretation remain
entirely human-led.

## Directory Layout

```text
river-engine/
+-- config/
|   +-- settings.yaml        # determinand list, thresholds, paths
+-- data/
|   +-- raw/                 # EA downloads land here
|   +-- processed/           # regenerated parquet files
|   +-- output/              # ranked feed and release outputs
+-- frontend/
|   +-- public/              # static frontend assets and data copy
|   +-- src/                 # React source
+-- notebooks/               # Research notebooks (reference only)
+-- src/
|   +-- 01_ingest.py
|   +-- 02_fingerprint.py
|   +-- 03_score.py
|   +-- 04_narrate.py
|   +-- run_pipeline.py      # chains all four layers
|   +-- utils.py             # shared helpers
+-- tests/
+-- README.md
```

## Data Ownership

This project uses publicly available Environment Agency open data. The research
was conducted independently on personal time and equipment.

GitHub: github.com/syedameersohail/River-Chemical-Fingerprints-England
