"""
Layer 1 - INGEST
================
Load Environment Agency freshwater monitoring data, clean it, and save a tidy
parquet file ready for fingerprinting.

Input:  EA bulk CSV exports or stitched parquet files in data/raw/
Output: data/processed/cleaned_observations.parquet
"""

import re
from pathlib import Path

import polars as pl

from utils import load_config, get_path, setup_logger, stage_stats, ensure_dir


log = setup_logger("01_ingest")


# Canonical names used by the downstream pipeline.
RENAME = {
    # EA API / bulk download column names used in the notebook.
    "id": "observation_id",
    "samplingPoint.notation": "site_id",
    "samplingPoint.prefLabel": "site_label",
    "samplingPoint.longitude": "lon",
    "samplingPoint.latitude": "lat",
    "samplingPoint.region": "region",
    "samplingPoint.area": "area",
    "samplingPoint.subArea": "sub_area",
    "samplingPoint.samplingPointStatus": "site_status",
    "samplingPoint.samplingPointType": "site_type",
    "phenomenonTime": "sample_datetime",
    "samplingPurpose": "sampling_purpose",
    "sampleMaterialType": "sample_material",
    "determinand.notation": "determinand_code",
    "determinand.prefLabel": "determinant",
    "unit": "unit",
    # Older / expanded EA linked-data column names.
    "sample.samplingPoint.notation": "site_id",
    "sample.samplingPoint.label": "site_label",
    "sample.samplingPoint.lat": "lat",
    "sample.samplingPoint.long": "lon",
    "sample.sampleDateTime": "sample_datetime",
    "sample.sampledMaterialType.label": "sample_material",
    "determinand.definition": "determinant",
    "determinand.unit.label": "unit",
    "result": "result_raw",
}

NOTEBOOK_EXCLUDE_UNITS = {
    "Text Result",
    "Coded Result",
    "PRESENT/NOT FOUND",
    "COLOUR",
}

NOTEBOOK_EXCLUDE_DETERMINANDS = {
    "Ionic Balance",
    "Equiv.Carbon No >10-35, Aliphatic Fraction",
    "Equiv.Carbon No >10-20, Aromatic Fraction",
    "Equiv.Carbon No >5-40",
}

BAD_DETERMINAND_PATTERNS = [
    r"(?i)\bionic balance\b",
    r"(?i)equiv\.?\s*carbon",
]

AREA_YEAR_RE = re.compile(r"obs_area-(\d+)_(\d{4})\.csv$", re.IGNORECASE)
SKIP_YEARS = {2014}


def _require_columns(df: pl.DataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            "Raw data is missing required columns after rename: "
            + ", ".join(missing)
            + ". Check that the CSVs are Environment Agency observation exports."
        )


def load_raw(raw_dir: Path) -> pl.DataFrame:
    """
    Load raw EA CSV/parquet files from data/raw/.

    Files named like obs_area-<area_id>_<year>.csv get area_id and source_year
    columns, matching the notebook download convention. The notebook skipped
    2014, so those files are ignored here when they are present.
    """
    files = sorted([*raw_dir.glob("*.csv"), *raw_dir.glob("*.parquet")])
    if not files:
        raise FileNotFoundError(f"No CSV or parquet files found in {raw_dir}")

    log.info(f"Loading {len(files)} raw file(s) from {raw_dir}")

    frames = []
    skipped = []
    for path in files:
        if path.suffix.lower() == ".parquet":
            frames.append(pl.read_parquet(path))
            continue

        match = AREA_YEAR_RE.search(path.name)
        if match:
            area_id, year = match.groups()
            year = int(year)
            if year in SKIP_YEARS:
                skipped.append(path.name)
                continue

            frame = pl.read_csv(path, infer_schema_length=10_000)
            frame = frame.with_columns(
                pl.lit(int(area_id)).alias("area_id"),
                pl.lit(year).alias("source_year"),
            )
        else:
            frame = pl.read_csv(path, infer_schema_length=10_000)

        frames.append(frame)

    if skipped:
        log.info(f"Skipped {len(skipped)} raw file(s) for years: {sorted(SKIP_YEARS)}")
    if not frames:
        raise FileNotFoundError(f"No usable CSV files found in {raw_dir}")

    return pl.concat(frames, how="diagonal")


def clean(df: pl.DataFrame, config: dict) -> pl.DataFrame:
    """
    Full cleaning pipeline mirrored from the notebook:
      1. Rename columns
      2. Filter to river/running surface water
      3. Remove derived determinands
      4. Remove non-quantitative units
      5. Parse numeric values, including left-censored <x as x/2
      6. Parse datetime and year
      7. Drop invalid rows
    """

    rename_map = {k: v for k, v in RENAME.items() if k in df.columns}
    df = df.rename(rename_map)

    _require_columns(
        df,
        [
            "site_id",
            "sample_material",
            "determinand_code",
            "determinant",
            "result_raw",
            "unit",
            "sample_datetime",
        ],
    )

    df = df.with_columns(
        pl.col("determinand_code").cast(pl.Utf8),
        pl.col("sample_material").cast(pl.Utf8),
        pl.col("determinant").cast(pl.Utf8),
        pl.col("unit").cast(pl.Utf8),
    )
    stage_stats(df, "After rename", log)

    keep_materials = config["keep_materials"]
    df = df.filter(pl.col("sample_material").is_in(keep_materials))
    stage_stats(df, "After material filter", log)

    exclude_determinands = set(config["exclude_determinands"]) | NOTEBOOK_EXCLUDE_DETERMINANDS
    df = df.filter(~pl.col("determinant").is_in(list(exclude_determinands)))
    for pattern in BAD_DETERMINAND_PATTERNS:
        df = df.filter(~pl.col("determinant").str.contains(pattern))
    stage_stats(df, "After determinand exclusions", log)

    exclude_units = set(config["exclude_units"]) | NOTEBOOK_EXCLUDE_UNITS
    df = df.filter(~pl.col("unit").is_in(list(exclude_units)))
    stage_stats(df, "After unit filter", log)

    censor_factor = config["censored_factor"]
    df = (
        df.with_columns(
            pl.when(pl.col("result_raw").is_null())
            .then(None)
            .otherwise(pl.col("result_raw").cast(pl.Utf8).str.strip_chars())
            .alias("_result_text")
        )
        .with_columns(
            pl.col("_result_text").str.starts_with("<").alias("is_left_censored"),
            pl.when(pl.col("_result_text").str.starts_with("<"))
            .then(
                pl.col("_result_text").str.slice(1).cast(pl.Float64, strict=False)
                * censor_factor
            )
            .otherwise(pl.col("_result_text").cast(pl.Float64, strict=False))
            .alias("value"),
        )
        .with_columns(
            pl.when(
                (pl.col("determinant") == "Alkalinity to pH 4.5 : Grans Plot")
                & (pl.col("value") < 0)
            )
            .then(0.0)
            .otherwise(pl.col("value"))
            .alias("value")
        )
        .drop("_result_text")
    )
    stage_stats(df, "After numeric parsing", log)

    df = df.filter(
        ~((pl.col("determinant") == "Temperature of Water") & (pl.col("value") > 45))
    )
    stage_stats(df, "After physical value filter", log)

    df = df.with_columns(
        pl.col("sample_datetime").cast(pl.Datetime, strict=False).alias("sample_dt")
    ).with_columns(pl.col("sample_dt").dt.year().alias("year"))

    before = df.height
    df = df.filter(
        pl.col("value").is_not_null()
        & pl.col("sample_dt").is_not_null()
        & pl.col("site_id").is_not_null()
    )
    log.info(f"Dropped {before - df.height:,} rows with null value/datetime/site_id")
    stage_stats(df, "Final cleaned dataset", log)

    return df


def run():
    """Execute the ingest layer."""
    config = load_config()

    raw_dir = get_path(config, "raw_data")
    out_dir = ensure_dir(get_path(config, "processed_data"))

    log.info("=" * 60)
    log.info("LAYER 1 - INGEST")
    log.info("=" * 60)

    df = load_raw(raw_dir)
    stage_stats(df.rename({k: v for k, v in RENAME.items() if k in df.columns}), "Raw loaded", log)

    df = clean(df, config)

    out_path = out_dir / "cleaned_observations.parquet"
    df.write_parquet(out_path)
    log.info(f"Saved -> {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    run()
