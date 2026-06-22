"""
Layer 2 - FINGERPRINT
=====================
Take cleaned observations and produce:
  1. Site x determinand chemical signatures
  2. A 2D UMAP embedding per site
  3. Optional WFD typology labels joined from a lookup file

Input:  data/processed/cleaned_observations.parquet
Output: data/processed/site_fingerprints.parquet
        data/processed/site_det_stats_2015_2024.parquet
        data/processed/umap_model.pkl
"""

import pickle
from pathlib import Path

import numpy as np
import polars as pl

from utils import load_config, get_path, setup_logger, ensure_dir


log = setup_logger("02_fingerprint")


META_COLS = [
    "site_id",
    "site_label",
    "lon",
    "lat",
    "region",
    "area",
    "sub_area",
    "site_type",
    "site_status",
]

OBSERVATION_META_COLS = [
    "first_sample",
    "last_sample",
    "total_observations",
    "distinct_sample_dates",
    "avg_days_between_visits",
]

YEAR_START = 2015
YEAR_END = 2024
MIN_SITES_PER_DETERMINAND = 200
MIN_OBS_PER_SITE_DETERMINAND = 30
MIN_FEATURE_COVERAGE = 0.60
MAX_MISSING_FEATURES = 3


def _code_key(code: object) -> str:
    text = str(code).strip()
    stripped = text.lstrip("0")
    return stripped or text


def _normalise_input(df: pl.DataFrame) -> pl.DataFrame:
    """Smooth over notebook/pipeline naming differences."""
    rename = {}
    if "determinant_code" in df.columns and "determinand_code" not in df.columns:
        rename["determinant_code"] = "determinand_code"
    if "site_name" in df.columns and "site_label" not in df.columns:
        rename["site_name"] = "site_label"
    if "datetime" in df.columns and "sample_dt" not in df.columns:
        rename["datetime"] = "sample_dt"
    if rename:
        df = df.rename(rename)

    if "year" not in df.columns and "sample_dt" in df.columns:
        df = df.with_columns(pl.col("sample_dt").dt.year().alias("year"))

    required = ["site_id", "determinand_code", "determinant", "unit", "value", "year"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Cleaned observations missing required columns: " + ", ".join(missing))

    return df.with_columns(
        pl.col("site_id").cast(pl.Utf8),
        pl.col("determinand_code").cast(pl.Utf8),
        pl.col("determinant").cast(pl.Utf8),
        pl.col("unit").cast(pl.Utf8),
        pl.col("value").cast(pl.Float64),
    )


def _first_existing(columns: list[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def build_site_determinant_stats(df: pl.DataFrame) -> pl.DataFrame:
    """Notebook cells 7-8: per-site/per-determinand summary stats."""
    dt_col = _first_existing(df.columns, "sample_dt", "sample_datetime")
    group_cols = ["site_id", "determinand_code", "unit"]

    agg_exprs = [
        pl.len().alias("n"),
        pl.col("value").mean().alias("mean"),
        pl.col("value").median().alias("median"),
        pl.col("value").std().alias("std"),
        pl.col("value").min().alias("min"),
        pl.col("value").max().alias("max"),
        pl.col("value").quantile(0.10).alias("q10"),
        pl.col("value").quantile(0.90).alias("q90"),
        pl.col("determinant").drop_nulls().first().alias("determinant"),
    ]
    if dt_col:
        agg_exprs.extend(
            [
                pl.col(dt_col).min().alias("dt_min"),
                pl.col(dt_col).max().alias("dt_max"),
            ]
        )

    stats = (
        df.lazy()
        .filter(pl.col("year").is_between(YEAR_START, YEAR_END))
        .group_by(group_cols)
        .agg(agg_exprs)
        .collect(streaming=True)
    )
    log.info(f"Built site-determinand stats: {stats.height:,} rows")
    return stats


def _panel_lookup(panel: dict[str, str]) -> dict[str, tuple[str, str]]:
    return {_code_key(code): (str(code), name) for code, name in panel.items()}


def choose_feature_determinands(
    site_det_stats: pl.DataFrame,
    config: dict,
) -> tuple[pl.DataFrame, dict[str, str]]:
    """
    Notebook cells 11 and 14:
    choose determinands with enough observations/sites, preferring configured
    common-core panel codes when they are present in the data.
    """
    panel = config["common_core_panel"]
    panel_by_key = _panel_lookup(panel)

    available_codes = (
        site_det_stats.select("determinand_code")
        .unique()
        .with_columns(
            pl.col("determinand_code").map_elements(_code_key, return_dtype=pl.Utf8).alias("code_key")
        )
    )

    panel_matches = available_codes.filter(pl.col("code_key").is_in(list(panel_by_key)))
    if panel_matches.height:
        selected = site_det_stats.join(
            panel_matches.select("determinand_code"), on="determinand_code", how="inner"
        )
        code_to_feature = {
            row["determinand_code"]: panel_by_key[_code_key(row["determinand_code"])][1]
            for row in panel_matches.iter_rows(named=True)
        }
        log.info(
            f"Using configured common-core panel: {len(code_to_feature)}/{len(panel)} "
            "codes matched the cleaned data"
        )
        return selected, code_to_feature

    good_dets = (
        site_det_stats.lazy()
        .filter(pl.col("n") >= MIN_OBS_PER_SITE_DETERMINAND)
        .group_by(["determinand_code", "unit"])
        .agg(
            pl.col("site_id").n_unique().alias("n_sites"),
            pl.col("n").median().alias("median_n_per_site"),
            pl.col("determinant").drop_nulls().first().alias("determinant"),
        )
        .filter(pl.col("n_sites") >= MIN_SITES_PER_DETERMINAND)
        .collect(streaming=True)
    )
    if good_dets.is_empty():
        raise ValueError(
            "No determinands passed the notebook coverage thresholds. "
            "You may need more raw data years/basins in data/raw."
        )

    selected = site_det_stats.join(
        good_dets.select(["determinand_code", "unit"]),
        on=["determinand_code", "unit"],
        how="inner",
    )
    code_to_feature = {
        row["determinand_code"]: row["determinant"] or row["determinand_code"]
        for row in good_dets.iter_rows(named=True)
    }
    log.warning(
        "Configured common-core panel did not match the data; using notebook "
        f"coverage-based selection ({len(code_to_feature)} determinands)"
    )
    return selected, code_to_feature


def build_site_metadata(df: pl.DataFrame) -> pl.DataFrame:
    """Notebook cell 13: one metadata row per site."""
    exprs = []
    for col in META_COLS:
        if col == "site_id":
            continue
        if col in df.columns:
            exprs.append(pl.col(col).drop_nulls().first().alias(col))
        else:
            exprs.append(pl.lit(None).cast(pl.Utf8).alias(col))

    return df.group_by("site_id").agg(exprs)


def build_site_observation_metadata(df: pl.DataFrame) -> pl.DataFrame:
    """Per-site sampling coverage used for frontend confidence indicators."""
    dt_col = _first_existing(df.columns, "sample_dt", "sample_datetime")
    if dt_col is None:
        return df.group_by("site_id").agg(
            pl.lit(None).cast(pl.Date).alias("first_sample"),
            pl.lit(None).cast(pl.Date).alias("last_sample"),
            pl.col("value").count().alias("total_observations"),
            pl.lit(None).cast(pl.UInt32).alias("distinct_sample_dates"),
            pl.lit(None).cast(pl.Float64).alias("avg_days_between_visits"),
        )

    return (
        df.group_by("site_id")
        .agg(
            pl.col(dt_col).min().alias("first_sample"),
            pl.col(dt_col).max().alias("last_sample"),
            pl.col("value").count().alias("total_observations"),
            pl.col(dt_col).n_unique().alias("distinct_sample_dates"),
        )
        .with_columns(
            pl.when(pl.col("distinct_sample_dates") > 1)
            .then(
                (pl.col("last_sample") - pl.col("first_sample")).dt.total_days()
                / pl.col("distinct_sample_dates")
            )
            .otherwise(None)
            .alias("avg_days_between_visits")
        )
    )


def build_signatures(df: pl.DataFrame, config: dict) -> pl.DataFrame:
    """
    Build the site chemistry matrix from cleaned observations.

    This follows notebook cells 7-19, but names feature columns with readable
    labels so layer 3 can use them directly.
    """
    df = _normalise_input(df)

    site_det_stats = build_site_determinant_stats(df)
    return build_signatures_from_stats(df, site_det_stats, config)


def build_signatures_from_stats(
    df: pl.DataFrame,
    site_det_stats: pl.DataFrame,
    config: dict,
) -> pl.DataFrame:
    """Build the site chemistry matrix from precomputed site-determinand stats."""
    selected_stats, code_to_feature = choose_feature_determinands(site_det_stats, config)

    site_det = selected_stats.with_columns(
        pl.col("determinand_code")
        .map_elements(lambda code: code_to_feature.get(code, code), return_dtype=pl.Utf8)
        .alias("feature_name")
    )

    site_matrix = site_det.pivot(
        on="feature_name",
        values="median",
        index="site_id",
        aggregate_function="first",
    )

    site_meta = build_site_metadata(df).join(
        build_site_observation_metadata(df),
        on="site_id",
        how="left",
    )
    signatures = site_meta.join(site_matrix, on="site_id", how="inner")

    metadata_cols = META_COLS + OBSERVATION_META_COLS
    feature_cols = [c for c in signatures.columns if c not in metadata_cols]
    if not feature_cols:
        raise ValueError("No feature columns were created from the cleaned observations.")

    coverage = signatures.select(
        [pl.col(c).is_not_null().mean().alias(c) for c in feature_cols]
    )
    keep_features = [c for c in feature_cols if coverage.select(pl.col(c)).item() >= MIN_FEATURE_COVERAGE]
    if not keep_features:
        raise ValueError("No feature columns met the 60% site coverage threshold.")

    signatures = signatures.select(metadata_cols + keep_features)

    signatures = signatures.with_columns(
        pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int8) for c in keep_features]).alias(
            "n_features_present"
        )
    )

    allowed_missing = min(MAX_MISSING_FEATURES, max(len(keep_features) - 1, 0))
    before = signatures.height
    signatures = signatures.filter(
        (len(keep_features) - pl.col("n_features_present")) <= allowed_missing
    )

    log.info(
        f"Signatures built: {signatures.height:,} sites, "
        f"{len(keep_features)} features kept, {before - signatures.height:,} sites dropped"
    )
    return signatures


def fit_umap(signatures: pl.DataFrame, config: dict) -> tuple[pl.DataFrame, object]:
    """
    Notebook cells 22 and 24-25:
    median-impute feature values, standard-scale them, then fit UMAP.
    """
    try:
        import umap
    except ImportError:
        log.error("umap-learn not installed. Run: pip install umap-learn")
        raise

    from sklearn.preprocessing import StandardScaler

    feature_cols = [
        c
        for c in signatures.columns
        if c not in META_COLS + OBSERVATION_META_COLS and c != "n_features_present"
    ]
    if not feature_cols:
        raise ValueError("No feature columns available for UMAP.")

    X_raw = signatures.select(feature_cols).to_numpy().astype(np.float64)
    col_medians = np.nanmedian(X_raw, axis=0)
    if np.isnan(col_medians).any():
        bad = [feature_cols[i] for i, val in enumerate(col_medians) if np.isnan(val)]
        raise ValueError("Cannot impute all-null feature columns: " + ", ".join(bad))

    X_imputed = X_raw.copy()
    row_idx, col_idx = np.where(np.isnan(X_imputed))
    X_imputed[row_idx, col_idx] = col_medians[col_idx]

    scaler = StandardScaler(with_mean=True, with_std=True)
    X_scaled = scaler.fit_transform(X_imputed)

    umap_cfg = config["umap"]
    reducer = umap.UMAP(
        n_neighbors=umap_cfg.get("n_neighbours", 15),
        min_dist=umap_cfg.get("min_dist", 0.1),
        n_components=umap_cfg.get("n_components", 2),
        metric=umap_cfg.get("metric", "euclidean"),
        random_state=umap_cfg.get("random_state", 42),
    )
    embedding = reducer.fit_transform(X_scaled)

    signatures = signatures.with_columns(
        [pl.Series(c, X_imputed[:, i]) for i, c in enumerate(feature_cols)]
        + [
            pl.Series("umap_x", embedding[:, 0]),
            pl.Series("umap_y", embedding[:, 1]),
        ]
    )

    log.info(f"UMAP fitted: {embedding.shape[0]:,} sites x {len(feature_cols)} features")

    return signatures, {
        "umap": reducer,
        "scaler": scaler,
        "feature_cols": feature_cols,
        "feature_medians": dict(zip(feature_cols, col_medians.tolist())),
    }


def _read_lookup(path: Path) -> pl.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)
    return pl.read_csv(path, infer_schema_length=10_000)


def join_wfd_typology(signatures: pl.DataFrame, proc_dir: Path) -> pl.DataFrame:
    """
    Join a prebuilt WFD lookup if available.

    Expected lookup filename:
      - data/processed/site_wfd_typology_lookup.csv/parquet, or
      - data/raw/site_wfd_typology_lookup.csv/parquet

    The notebook creates this lookup from the WFD Cycle 3 GeoPackage. The spatial
    join itself stays outside this pipeline layer because it needs geopandas and
    the large downloaded GeoPackage.
    """
    candidates = [
        proc_dir / "site_wfd_typology_lookup.parquet",
        proc_dir / "site_wfd_typology_lookup.csv",
        proc_dir.parent / "raw" / "site_wfd_typology_lookup.parquet",
        proc_dir.parent / "raw" / "site_wfd_typology_lookup.csv",
    ]
    lookup_path = next((p for p in candidates if p.exists()), None)

    if lookup_path is None:
        log.warning(
            "WFD typology lookup not found. Add site_wfd_typology_lookup.csv/parquet "
            "to data/processed or data/raw to populate wfd_type."
        )
        return signatures.with_columns(pl.lit(None).cast(pl.Utf8).alias("wfd_type"))

    lookup = _read_lookup(lookup_path)
    if "water_body_typology" in lookup.columns and "wfd_type" not in lookup.columns:
        lookup = lookup.rename({"water_body_typology": "wfd_type"})
    if "site_name" in lookup.columns and "site_label" not in lookup.columns:
        lookup = lookup.rename({"site_name": "site_label_wfd"})

    wanted = [
        c
        for c in [
            "site_id",
            "wfd_type",
            "water_body_id",
            "water_body_name",
            "water_body_type",
            "water_body_hmd",
            "ecological_class",
            "chemical_class",
            "overall_water_body_class",
            "dist_to_wfd_m",
        ]
        if c in lookup.columns
    ]
    if "site_id" not in wanted or "wfd_type" not in wanted:
        log.warning(f"WFD lookup {lookup_path} lacks site_id/wfd_type; leaving wfd_type null")
        return signatures.with_columns(pl.lit(None).cast(pl.Utf8).alias("wfd_type"))

    lookup = lookup.select(wanted).unique(subset=["site_id"], keep="first")
    joined = signatures.join(lookup, on="site_id", how="left")
    log.info(f"Joined WFD typology from {lookup_path}")
    return joined


def run():
    """Execute the fingerprint layer."""
    config = load_config()

    proc_dir = ensure_dir(get_path(config, "processed_data"))
    input_path = proc_dir / "cleaned_observations.parquet"

    log.info("=" * 60)
    log.info("LAYER 2 - FINGERPRINT")
    log.info("=" * 60)

    df = pl.read_parquet(input_path)
    log.info(f"Loaded {df.height:,} cleaned observations")

    normalised = _normalise_input(df)
    stats = build_site_determinant_stats(normalised)
    stats_path = proc_dir / f"site_det_stats_{YEAR_START}_{YEAR_END}.parquet"
    stats.write_parquet(stats_path)
    log.info(f"Saved stats -> {stats_path}")

    signatures = build_signatures_from_stats(normalised, stats, config)
    signatures, models = fit_umap(signatures, config)
    signatures = join_wfd_typology(signatures, proc_dir)

    out_path = proc_dir / "site_fingerprints.parquet"
    signatures.write_parquet(out_path)
    log.info(f"Saved -> {out_path} ({signatures.height:,} sites)")

    model_path = proc_dir / "umap_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(models, f)
    log.info(f"Saved models -> {model_path}")


if __name__ == "__main__":
    run()
