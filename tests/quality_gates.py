"""
Release quality gates for the River Signal pipeline.

Each gate returns structured check results so the CLI runner and the pipeline
can halt cleanly with a useful report when a release candidate is not ready.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import polars as pl

try:
    from scipy.stats import skew as scipy_skew
    from scipy.stats import spearmanr
except ImportError:  # pragma: no cover - fallback keeps the gates usable in lean envs.
    scipy_skew = None
    spearmanr = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
ARCHIVE_DIR = PROJECT_ROOT / "data" / "archive"

COMMON_CORE_CODES = ["76", "61", "162", "77", "9924", "118", "117", "111", "180", "116", "119", "9901"]
DOWNSTREAM_COLUMNS = ["site_id", "lat", "lon", "determinand_code", "value"]


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: dict[str, Any] | None = None


@dataclass
class GateResult:
    gate_name: str
    passed: bool
    checks: list[CheckResult]
    timestamp: str


def gate_1_data_sanity(config: dict) -> GateResult:
    """Validate cleaned observations before fingerprinting.

    This gate catches major ingestion regressions: missing core determinands,
    broken coordinates, sparse coverage, invalid values, and unexpected changes
    in row counts compared with the previous archived run.
    """

    settings = _gate_config(config, "gate_1")
    path = _processed_path(config, "cleaned_observations.parquet")
    checks: list[CheckResult] = []

    if not path.exists():
        return _gate_result("Gate 1 - Data Sanity", [_fail("Input file exists", f"Missing {path}")])

    df = pl.read_parquet(path)
    columns = set(df.columns)
    n_rows = df.height

    previous_meta = _load_latest_json("cleaned_observations_meta.json") or _load_latest_json("gate1_meta.json")
    tolerance = float(settings.get("row_count_tolerance", 0.15))
    if previous_meta and previous_meta.get("row_count"):
        previous_rows = int(previous_meta["row_count"])
        lower = previous_rows * (1 - tolerance)
        upper = previous_rows * (1 + tolerance)
        passed = lower <= n_rows <= upper
        checks.append(
            CheckResult(
                "Row count tolerance",
                passed,
                f"{n_rows:,} rows; expected {lower:,.0f}-{upper:,.0f} from previous {previous_rows:,}",
                {"row_count": n_rows, "previous_row_count": previous_rows, "tolerance": tolerance},
            )
        )
    else:
        floor = 5_000_000
        checks.append(
            CheckResult(
                "Row count floor",
                n_rows >= floor,
                f"{n_rows:,} rows; first-run floor is {floor:,}",
                {"row_count": n_rows, "min_row_count": floor},
            )
        )

    site_count = _n_unique(df, "site_id")
    min_site_count = int(settings.get("min_site_count", 10_000))
    checks.append(
        CheckResult(
            "Site count floor",
            site_count >= min_site_count,
            f"{site_count:,} unique sites; minimum is {min_site_count:,}",
            {"site_count": site_count, "min_site_count": min_site_count},
        )
    )

    determinand_codes = _string_values(df, "determinand_code")
    missing_codes = [code for code in COMMON_CORE_CODES if code not in determinand_codes]
    checks.append(
        CheckResult(
            "Determinand coverage",
            not missing_codes,
            "All common-core determinands present" if not missing_codes else f"Missing codes: {', '.join(missing_codes)}",
            {"missing_codes": missing_codes, "present_count": len(determinand_codes)},
        )
    )

    max_null_rate = float(settings.get("max_null_rate", 0.05))
    null_rates: dict[str, float | None] = {}
    null_failures: dict[str, float] = {}
    for column in DOWNSTREAM_COLUMNS:
        if column not in columns:
            null_rates[column] = None
            null_failures[column] = 1.0
            continue
        rate = df.select(pl.col(column).is_null().mean()).item()
        null_rates[column] = float(rate or 0)
        if rate and rate > max_null_rate:
            null_failures[column] = float(rate)
    checks.append(
        CheckResult(
            "Null rate",
            not null_failures,
            "Downstream columns are below null-rate threshold"
            if not null_failures
            else f"Columns above threshold: {', '.join(null_failures)}",
            {"null_rates": null_rates, "max_null_rate": max_null_rate},
        )
    )

    range_failures = _value_range_failures(df, settings.get("value_ranges", {}))
    checks.append(
        CheckResult(
            "Value range sanity",
            not range_failures,
            "Core chemical values are inside configured ranges and values are non-negative"
            if not range_failures
            else f"Range failures: {', '.join(range_failures)}",
            {"failures": range_failures},
        )
    )

    years = _distinct_years(df)
    latest_year = max(years) if years else None
    current_year = datetime.now().year
    min_years = int(settings.get("min_years", 5))
    temporal_passed = len(years) >= min_years and latest_year is not None and current_year - latest_year <= 2
    checks.append(
        CheckResult(
            "Temporal coverage",
            temporal_passed,
            f"{len(years)} distinct years; latest year is {latest_year}",
            {"years": years, "min_years": min_years, "latest_year": latest_year},
        )
    )

    regions = _regions(df)
    min_regions = int(settings.get("min_regions", 5))
    checks.append(
        CheckResult(
            "Regional coverage",
            len(regions) >= min_regions,
            f"{len(regions)} regions/site prefixes found; minimum is {min_regions}",
            {"regions": regions, "min_regions": min_regions},
        )
    )

    result = _gate_result("Gate 1 - Data Sanity", checks)
    if result.passed:
        _write_json(
            _processed_path(config, "gate1_meta.json"),
            {
                "timestamp": result.timestamp,
                "row_count": n_rows,
                "site_count": site_count,
                "determinand_codes": sorted(determinand_codes),
                "date_range": _date_range(df),
                "regions": regions,
            },
        )
    return result


def gate_2_ranking_quality(config: dict) -> GateResult:
    """Validate anomaly ranking quality before narration.

    This gate protects the ranking layer by checking known-answer sites, rank
    stability, score distribution shape, flag volume, driver presence, and peer
    group coverage.
    """

    settings = _gate_config(config, "gate_2")
    path = _processed_path(config, "scored_sites.parquet")
    checks: list[CheckResult] = []

    if not path.exists():
        return _gate_result("Gate 2 - Ranking Quality", [_fail("Input file exists", f"Missing {path}")])

    df = pl.read_parquet(path)

    known_bad = list(settings.get("known_bad_sites", []))
    max_bad_rank = int(settings.get("known_bad_max_rank", 50))
    bad_details = _site_rank_details(df, known_bad)
    missing_bad = [
        item for item in bad_details if item["rank"] is None or int(item["rank"]) > max_bad_rank
    ]
    checks.append(
        CheckResult(
            "Known bad sites",
            not missing_bad,
            "All known-bad sites are in the top 50"
            if not missing_bad
            else f"{len(missing_bad)} known-bad sites missing from top {max_bad_rank}",
            {"sites": bad_details, "missing_or_low_rank": missing_bad},
        )
    )

    known_clean = list(settings.get("known_clean_sites", []))
    clean_min_rank = int(settings.get("known_clean_min_rank", 500))
    clean_details = _site_rank_details(df, known_clean)
    clean_failures = [
        item for item in clean_details if item["rank"] is not None and int(item["rank"]) <= clean_min_rank
    ]
    checks.append(
        CheckResult(
            "Known clean sites",
            not clean_failures,
            "No known-clean sites are in the top 500" if not clean_failures else f"{len(clean_failures)} clean sites rank too high",
            {"sites": clean_details, "unexpected_top_sites": clean_failures},
        )
    )

    previous_scored = _latest_archive_file("scored_sites.parquet")
    if previous_scored:
        stability = _rank_stability(df, pl.read_parquet(previous_scored), float(settings.get("min_spearman", 0.85)))
        checks.append(stability)
    else:
        checks.append(
            CheckResult(
                "Rank stability",
                True,
                "No previous run to compare against - skipping stability check.",
                {"skipped": True},
            )
        )

    scores = df.select(pl.col("anomaly_score").drop_nulls()).to_series().to_list()
    skew_value = _skew(scores)
    min_skewness = float(settings.get("min_skewness", 1.0))
    checks.append(
        CheckResult(
            "Score distribution shape",
            skew_value is not None and skew_value > min_skewness,
            f"Anomaly score skewness is {skew_value:.3f}" if skew_value is not None else "Could not compute skewness",
            {"skewness": skew_value, "min_skewness": min_skewness},
        )
    )

    flagged_count = int(df.filter(pl.col("is_flagged") == True).height) if "is_flagged" in df.columns else 0
    flagged_min, flagged_max = settings.get("flagged_count_range", [200, 800])
    checks.append(
        CheckResult(
            "Flagged count band",
            int(flagged_min) <= flagged_count <= int(flagged_max),
            f"{flagged_count:,} flagged sites; expected {int(flagged_min):,}-{int(flagged_max):,}",
            {"flagged_count": flagged_count, "range": [flagged_min, flagged_max]},
        )
    )

    top_20 = df.sort("anomaly_rank").head(20)
    if "anomaly_drivers" in top_20.columns:
        empty_drivers = top_20.filter(
            pl.col("anomaly_drivers").is_null() | (pl.col("anomaly_drivers").cast(pl.Utf8).str.strip_chars() == "")
        ).select(["site_id", "anomaly_rank"]).to_dicts()
    else:
        empty_drivers = top_20.select(["site_id", "anomaly_rank"]).to_dicts()
    checks.append(
        CheckResult(
            "Driver plausibility",
            not empty_drivers,
            "Top 20 sites all have anomaly drivers" if not empty_drivers else f"{len(empty_drivers)} top-20 sites lack drivers",
            {"empty_driver_sites": empty_drivers},
        )
    )

    peer_details = _peer_group_coverage(df)
    max_global = float(settings.get("max_global_fallback_pct", 0.10))
    checks.append(
        CheckResult(
            "Peer group coverage",
            peer_details["global_pct"] <= max_global,
            f"{peer_details['global_pct']:.1%} of sites used global fallback",
            {**peer_details, "max_global_fallback_pct": max_global},
        )
    )

    result = _gate_result("Gate 2 - Ranking Quality", checks)
    if result.passed:
        _write_json(
            _processed_path(config, "gate2_meta.json"),
            {
                "timestamp": result.timestamp,
                "site_count": df.height,
                "flagged_count": flagged_count,
                "score_skewness": skew_value,
                "peer_group_coverage": peer_details,
            },
        )
    return result


def gate_3_output_quality(config: dict) -> GateResult:
    """Validate the publishable ranked feed.

    This gate makes sure the final JSON is parseable, schema-complete, narrated
    for flagged sites, geographically plausible, rank-continuous, and within an
    expected file-size range. The release diff is informational only.
    """

    settings = _gate_config(config, "gate_3")
    path = _output_path(config, "ranked_feed.json")
    checks: list[CheckResult] = []
    feed: list[dict[str, Any]] = []
    payload: Any = None

    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        feed = _extract_feed(payload)
        checks.append(CheckResult("JSON validity", True, f"Parsed {path}", {"entries": len(feed)}))
    except Exception as exc:
        checks.append(_fail("JSON validity", f"Could not parse {path}: {exc}"))
        return _gate_result("Gate 3 - Output Quality", checks)

    required = ["site_id", "site_label", "lat", "lon", "anomaly_rank", "anomaly_score", "is_flagged"]
    flagged_required = ["drivers", "summary"]
    missing_required: list[dict[str, Any]] = []
    for item in feed:
        missing = [field for field in required if field not in item]
        if item.get("is_flagged"):
            missing.extend(field for field in flagged_required if field not in item)
        if missing:
            missing_required.append({"site_id": item.get("site_id"), "missing": missing})
    checks.append(
        CheckResult(
            "Schema completeness",
            not missing_required,
            "All entries include required fields" if not missing_required else f"{len(missing_required)} entries are missing fields",
            {"missing": missing_required[:50], "total_missing": len(missing_required)},
        )
    )

    min_summary_length = int(settings.get("min_summary_length", 50))
    narrative_failures = []
    for item in feed:
        if not item.get("is_flagged"):
            continue
        summary = item.get("summary")
        if not isinstance(summary, str) or len(summary.strip()) <= min_summary_length or summary.strip().endswith("..."):
            narrative_failures.append({"site_id": item.get("site_id"), "rank": item.get("anomaly_rank")})
    checks.append(
        CheckResult(
            "Narrative completeness",
            not narrative_failures,
            "All flagged sites have complete summaries" if not narrative_failures else f"{len(narrative_failures)} flagged sites have weak summaries",
            {"failures": narrative_failures[:50], "total_failures": len(narrative_failures)},
        )
    )

    lat_min, lat_max = settings.get("lat_bounds", [49.9, 55.8])
    lon_min, lon_max = settings.get("lon_bounds", [-6.4, 1.8])
    bad_coords = [
        {"site_id": item.get("site_id"), "lat": item.get("lat"), "lon": item.get("lon")}
        for item in feed
        if not _within_number(item.get("lat"), lat_min, lat_max) or not _within_number(item.get("lon"), lon_min, lon_max)
    ]
    checks.append(
        CheckResult(
            "Coordinate bounds",
            not bad_coords,
            "All coordinates are within England bounds" if not bad_coords else f"{len(bad_coords)} entries have out-of-bounds coordinates",
            {"bad_coordinates": bad_coords[:50], "total_bad_coordinates": len(bad_coords)},
        )
    )

    ranks = [item.get("anomaly_rank") for item in feed if isinstance(item.get("anomaly_rank"), int)]
    expected = list(range(1, len(feed) + 1))
    checks.append(
        CheckResult(
            "Rank continuity",
            sorted(ranks) == expected,
            "Ranks form a continuous sequence from 1 to N"
            if sorted(ranks) == expected
            else "Ranks contain gaps, duplicates, or non-integer values",
            {"rank_count": len(ranks), "entry_count": len(feed)},
        )
    )

    min_mb, max_mb = settings.get("file_size_mb_range", [1, 15])
    size_mb = path.stat().st_size / (1024 * 1024)
    checks.append(
        CheckResult(
            "File size band",
            float(min_mb) <= size_mb <= float(max_mb),
            f"Output size is {size_mb:.2f} MB; expected {float(min_mb):.1f}-{float(max_mb):.1f} MB",
            {"size_mb": size_mb, "range_mb": [min_mb, max_mb]},
        )
    )

    diff_report = _release_diff(feed)
    _write_json(_output_path(config, "release_diff.json"), diff_report)
    checks.append(CheckResult("Diff report", True, "Saved informational release diff", diff_report))

    result = _gate_result("Gate 3 - Output Quality", checks)
    if result.passed:
        _write_json(
            _output_path(config, "gate3_meta.json"),
            {
                "timestamp": result.timestamp,
                "entry_count": len(feed),
                "flagged_count": sum(1 for item in feed if item.get("is_flagged")),
                "file_size_mb": size_mb,
            },
        )
    return result


def result_to_dict(result: GateResult) -> dict[str, Any]:
    return asdict(result)


def _gate_config(config: dict, gate: str) -> dict:
    return dict(config.get("quality_gates", {}).get(gate, {}))


def _processed_path(config: dict, filename: str) -> Path:
    base = PROJECT_ROOT / config.get("paths", {}).get("processed_data", "data/processed")
    return base / filename


def _output_path(config: dict, filename: str) -> Path:
    base = PROJECT_ROOT / config.get("paths", {}).get("output", "data/output")
    return base / filename


def _gate_result(name: str, checks: list[CheckResult]) -> GateResult:
    return GateResult(name, all(check.passed for check in checks), checks, _timestamp())


def _fail(name: str, message: str, details: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name, False, message, details)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def _archive_dirs() -> list[Path]:
    if not ARCHIVE_DIR.exists():
        return []
    return sorted([path for path in ARCHIVE_DIR.iterdir() if path.is_dir()], reverse=True)


def _latest_archive_file(filename: str) -> Path | None:
    for archive in _archive_dirs():
        candidate = archive / filename
        if candidate.exists():
            return candidate
    return None


def _load_latest_json(filename: str) -> dict[str, Any] | None:
    path = _latest_archive_file(filename)
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _n_unique(df: pl.DataFrame, column: str) -> int:
    if column not in df.columns:
        return 0
    return int(df.select(pl.col(column).n_unique()).item())


def _string_values(df: pl.DataFrame, column: str) -> set[str]:
    if column not in df.columns:
        return set()
    return set(df.select(pl.col(column).drop_nulls().cast(pl.Utf8).unique()).to_series().to_list())


def _value_range_failures(df: pl.DataFrame, value_ranges: dict[str, list[float]]) -> dict[str, dict[str, Any]]:
    failures: dict[str, dict[str, Any]] = {}
    required = {"value", "determinant"}
    if not required.issubset(df.columns):
        return {"schema": {"message": "Missing value or determinant column"}}

    for determinant, bounds in value_ranges.items():
        if len(bounds) != 2:
            continue
        low, high = bounds
        subset = df.filter(pl.col("determinant") == determinant)
        if subset.is_empty():
            failures[determinant] = {"message": "No rows found for determinant"}
            continue
        count = subset.filter((pl.col("value") < float(low)) | (pl.col("value") > float(high))).height
        if count:
            failures[determinant] = {"out_of_range_count": count, "range": [low, high]}

    negative_count = df.filter(pl.col("value") < 0).height
    if negative_count:
        failures["non_negative_values"] = {"negative_count": negative_count}
    return failures


def _sample_datetime_column(df: pl.DataFrame) -> str | None:
    for column in ("sample_dt", "sample_datetime"):
        if column in df.columns:
            return column
    return None


def _distinct_years(df: pl.DataFrame) -> list[int]:
    column = _sample_datetime_column(df)
    if not column:
        return []
    return sorted(
        int(year)
        for year in df.select(pl.col(column).dt.year().drop_nulls().unique()).to_series().to_list()
    )


def _date_range(df: pl.DataFrame) -> dict[str, Any]:
    column = _sample_datetime_column(df)
    if not column:
        return {"min": None, "max": None}
    row = df.select(pl.col(column).min().alias("min"), pl.col(column).max().alias("max")).to_dicts()[0]
    return row


def _regions(df: pl.DataFrame) -> list[str]:
    if "region" in df.columns:
        return sorted(str(value) for value in df.select(pl.col("region").drop_nulls().unique()).to_series().to_list())
    if "site_id" not in df.columns:
        return []
    prefixes = (
        df.select(pl.col("site_id").drop_nulls().cast(pl.Utf8).str.split("-").list.first().alias("prefix"))
        .select(pl.col("prefix").unique())
        .to_series()
        .to_list()
    )
    return sorted(str(prefix) for prefix in prefixes if prefix)


def _site_rank_details(df: pl.DataFrame, site_ids: list[str]) -> list[dict[str, Any]]:
    if not site_ids:
        return []
    rows = (
        df.filter(pl.col("site_id").is_in(site_ids))
        .select(["site_id", "anomaly_rank"])
        .to_dicts()
    )
    ranks = {row["site_id"]: row["anomaly_rank"] for row in rows}
    return [{"site_id": site_id, "rank": ranks.get(site_id)} for site_id in site_ids]


def _rank_stability(current: pl.DataFrame, previous: pl.DataFrame, min_spearman: float) -> CheckResult:
    joined = current.select(["site_id", "anomaly_rank"]).join(
        previous.select(["site_id", "anomaly_rank"]),
        on="site_id",
        how="inner",
        suffix="_previous",
    )
    if joined.height < 2:
        return CheckResult("Rank stability", True, "Fewer than two overlapping sites - skipping stability check.", {"overlap": joined.height})

    old_ranks = joined["anomaly_rank_previous"].to_list()
    new_ranks = joined["anomaly_rank"].to_list()
    if spearmanr:
        correlation = float(spearmanr(old_ranks, new_ranks).statistic)
    else:
        correlation = _fallback_spearman(old_ranks, new_ranks)

    movers = (
        joined.with_columns((pl.col("anomaly_rank_previous") - pl.col("anomaly_rank")).abs().alias("rank_delta"))
        .sort("rank_delta", descending=True)
        .head(10)
        .select(["site_id", "anomaly_rank_previous", "anomaly_rank", "rank_delta"])
        .to_dicts()
    )
    return CheckResult(
        "Rank stability",
        correlation >= min_spearman,
        f"Spearman rank correlation is {correlation:.3f} across {joined.height:,} overlapping sites",
        {"spearman": correlation, "min_spearman": min_spearman, "overlap": joined.height, "largest_movers": movers},
    )


def _skew(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if len(clean) < 3:
        return None
    if scipy_skew:
        return float(scipy_skew(clean, bias=False))
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / (len(clean) - 1)
    if variance == 0:
        return 0.0
    std = variance**0.5
    return sum(((value - mean) / std) ** 3 for value in clean) / len(clean)


def _fallback_spearman(old_ranks: list[int], new_ranks: list[int]) -> float:
    n = len(old_ranks)
    if n < 2:
        return 1.0
    deltas = [float(old - new) for old, new in zip(old_ranks, new_ranks)]
    return 1 - (6 * sum(delta * delta for delta in deltas)) / (n * (n * n - 1))


def _peer_group_coverage(df: pl.DataFrame) -> dict[str, Any]:
    if "score_reference" not in df.columns or df.is_empty():
        return {"counts": {}, "global_count": df.height, "global_pct": 1.0}
    references = df.select(pl.col("score_reference").fill_null("unknown").cast(pl.Utf8)).to_series().to_list()
    counts = {
        "wfd_peers": sum("wfd" in value.lower() or "typology" in value.lower() or "low," in value.lower() for value in references),
        "geographic_neighbours": sum("geographic" in value.lower() or "neighbour" in value.lower() or "neighbor" in value.lower() for value in references),
        "global_fallback": sum("global" in value.lower() or "fallback" in value.lower() for value in references),
        "other": 0,
    }
    counts["other"] = max(0, len(references) - counts["wfd_peers"] - counts["geographic_neighbours"] - counts["global_fallback"])
    return {
        "counts": counts,
        "global_count": counts["global_fallback"],
        "global_pct": counts["global_fallback"] / len(references),
    }


def _extract_feed(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("feed"), list):
        return payload["feed"]
    return []


def _within_number(value: Any, low: float, high: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return float(low) <= number <= float(high)


def _release_diff(feed: list[dict[str, Any]]) -> dict[str, Any]:
    previous_path = _latest_archive_file("ranked_feed.json")
    if not previous_path:
        return {"previous_feed": None, "message": "No previous ranked_feed.json in archive."}
    with open(previous_path, encoding="utf-8") as handle:
        previous_feed = _extract_feed(json.load(handle))

    current_by_site = {item.get("site_id"): item for item in feed if item.get("site_id")}
    previous_by_site = {item.get("site_id"): item for item in previous_feed if item.get("site_id")}

    current_top_50 = {item.get("site_id") for item in feed if isinstance(item.get("anomaly_rank"), int) and item["anomaly_rank"] <= 50}
    previous_top_50 = {
        item.get("site_id") for item in previous_feed if isinstance(item.get("anomaly_rank"), int) and item["anomaly_rank"] <= 50
    }

    movers = []
    for site_id, item in current_by_site.items():
        old = previous_by_site.get(site_id)
        if not old:
            continue
        new_rank = item.get("anomaly_rank")
        old_rank = old.get("anomaly_rank")
        if isinstance(new_rank, int) and isinstance(old_rank, int) and (new_rank <= 200 or old_rank <= 200):
            movers.append(
                {
                    "site_id": site_id,
                    "old_rank": old_rank,
                    "new_rank": new_rank,
                    "rank_delta": old_rank - new_rank,
                }
            )

    movers_up = sorted(movers, key=lambda row: row["rank_delta"], reverse=True)[:10]
    movers_down = sorted(movers, key=lambda row: row["rank_delta"])[:10]
    return {
        "previous_feed": str(previous_path),
        "entered_top_50": sorted(site for site in current_top_50 - previous_top_50 if site),
        "exited_top_50": sorted(site for site in previous_top_50 - current_top_50 if site),
        "largest_movers_up": movers_up,
        "largest_movers_down": movers_down,
    }
