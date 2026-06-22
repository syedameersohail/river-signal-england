"""
Fetch, filter, deduplicate, and save EA pollution incident data and EDM sewage spill data.

Data sources (all Open Government Licence v3):
  1. Environmental Pollution Incidents (Category 1 & 2) — NIRS2 extract
     https://www.data.gov.uk/dataset/c8625e18-c329-4032-b4c7-444b33af6780
     ZIP contains EP_Incidents_Nirs2.csv + EP_Pollutants_Nirs2.csv

  2. Event Duration Monitoring — Storm Overflows Annual Return
     https://www.data.gov.uk/dataset/19f6064d-7356-466f-844e-d20ea10ae9fd
     ZIP per year, each containing an XLSX workbook with one sheet per water company.

To update URLs if they change:
  - Search https://ckan.publishing.service.gov.uk for the dataset IDs above.
  - The fileDataSetId in the download URLs may rotate when new versions are published.
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path

import polars as pl
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
TEMP_DIR = Path(__file__).resolve().parent.parent / "data" / "temp"

POLLUTION_ZIP_URL = (
    "https://environment.data.gov.uk/api/file/download"
    "?fileDataSetId=a5a11813-517a-478b-be89-4acdf2c1f105"
    "&fileName=Environmental%20Pollution%20Incidents%20(Category%201%20and%202).zip"
)

EDM_BASE_URL = (
    "https://environment.data.gov.uk/api/file/download"
    "?fileDataSetId=c55e170e-3c75-49a5-8026-a961ff94c8e0"
    "&fileName="
)
EDM_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]

# ---------------------------------------------------------------------------
# Scope-filtering keywords
# ---------------------------------------------------------------------------

# Pollutant types/names that signal freshwater-relevant incidents
WATER_RELEVANT_POLLUTANTS = {
    "Crude Sewage", "Storm Sewage", "Sludge", "Final Effluent",
    "Grey Water", "Other Sewage Material", "Backwash Effluent",
    "Slurry and Dilute Slurry", "Solid Manure", "Silage Liquors",
    "Dairy Washings", "Other Agricultural Material or Waste",
    "Fertiliser", "Blood and Offal", "Carcasses",
    "Other Animal Matter", "Vegetable Washings", "Vegetable Cuttings and Deposits",
    "Diesel", "Petrol", "Gas and Fuel Oils", "Crude Oil",
    "Kerosene and Aviation Fuel", "Unidentified Oil", "Mixed/Waste Oils",
    "Other Oil or Fuel", "Lubricating Oils", "Hydraulic Oils",
    "Cutting Oils", "Insulating and Cable Oils",
    "Paints and Varnishes", "Solvents", "Dyes and Inks",
    "Surfactants and Detergents", "Phenols and Creosote",
    "Pesticides and Biocides", "Sheep Dip",
    "Heavy Metals", "Acids", "Alkalis", "Cyanides", "Ammonia Solutions",
    "Chemically Contaminated Run-Off", "Other Contaminated Water",
    "Other Inorganic Chemical or Product", "Other Organic Chemical or Product",
    "Inorganic Chemical Wastes", "Organic Chemical Wastes",
    "Landfill Leachate", "Minewater", "Process Effluent",
    "Firefighting Run-Off", "Urban Run-Off",
    "Algae", "Natural Organic Material",
    "Effect on Animals", "Microbiological",
    "Suspended Solids",
}

# Pollutant types to always keep (entire category is water-relevant)
WATER_RELEVANT_POLL_TYPES = {
    "Sewage Materials",
    "Agricultural Materials and Wastes",
    "Oils and Fuel",
    "Organic Chemicals/Products",
    "Inorganic Chemicals/Products",
    "Contaminated Water",
}

# Pollutants that are out-of-scope
OUT_OF_SCOPE_POLLUTANTS = {
    "Noise", "Smoke", "Fumes", "Dust", "Steam",
    "Soot/Smuts", "Chemical Odour", "Ammonia/Amine Odour",
    "Sulphide Odour", "Landfill Odour", "Other Odour",
    "Other Atmospheric Pollutant or Effect",
    "Damage to Buildings, Vehicles and Vegetation",
    "Effects on Humans", "Flies", "Vermin",
    "Asbestos", "Batteries", "Electrical Equipment",
    "Tyres", "Vehicles and Vehicle Parts", "Containers",
    "Clinical Waste", "Prescription only medicines",
    "Radionucleid",
}


def _download(url: str, dest: Path, retries: int = 5) -> Path:
    print(f"  Downloading {dest.name} ...")
    import time
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=300, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            size = dest.stat().st_size
            print(f"  Downloaded {size:,} bytes")
            return dest
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            if attempt < retries:
                wait = 15 * attempt
                print(f"  Attempt {attempt} failed ({e}), retrying in {wait}s ...")
                time.sleep(wait)
            else:
                raise


def _extract_zip(zip_path: Path, extract_to: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_to)
    return extract_to


# ---------------------------------------------------------------------------
# 1. Pollution Incidents
# ---------------------------------------------------------------------------

def _parse_ngr_to_latlon(ngr_series: pl.Series) -> tuple[pl.Series, pl.Series]:
    """Convert OS National Grid References to approximate lat/lon.

    Uses a simple linear approximation (good to ~1 km) to avoid a pyproj
    dependency. Phase 2 spatial join will use precise coordinates anyway.
    """
    grid_letters = {
        "SV": (0, 0), "SW": (1, 0), "SX": (2, 0), "SY": (3, 0), "SZ": (4, 0),
        "TV": (5, 0), "TW": (6, 0),
        "SR": (1, 1), "SS": (2, 1), "ST": (3, 1), "SU": (4, 1),
        "SP": (4, 2), "TL": (5, 2), "TM": (6, 2),
        "SO": (3, 2), "SN": (2, 2), "SM": (1, 2),
        "SK": (4, 3), "TF": (5, 3), "TG": (6, 3),
        "SJ": (3, 3), "SH": (2, 3), "SG": (1, 3),
        "SE": (4, 4), "TA": (5, 4),
        "SD": (3, 4), "SC": (2, 4), "SB": (1, 4),
        "NZ": (4, 5), "OV": (5, 5),
        "NY": (3, 5), "NX": (2, 5), "NW": (1, 5),
        "NT": (4, 6), "NU": (5, 6),
        "NS": (3, 6), "NR": (2, 6), "NQ": (1, 6),
        "NN": (3, 7), "NO": (4, 7),
        "NM": (2, 7), "NL": (1, 7),
        "NH": (2, 8), "NJ": (3, 8), "NK": (4, 8),
        "NG": (1, 8), "NF": (0, 8),
        "NC": (2, 9), "ND": (3, 9),
        "NB": (1, 9), "NA": (0, 9),
        "HW": (1, 10), "HX": (2, 10), "HY": (3, 10), "HZ": (4, 10),
        "HP": (4, 11), "HT": (3, 11), "HU": (4, 11),
    }
    ngr_pattern = re.compile(
        r"^\s*([A-Z]{2})\s*(\d{2,10})\s*$", re.IGNORECASE
    )

    lats = []
    lons = []
    for val in ngr_series.to_list():
        if val is None:
            lats.append(None)
            lons.append(None)
            continue
        val_clean = str(val).replace(" ", "")
        m = ngr_pattern.match(val_clean)
        if not m:
            lats.append(None)
            lons.append(None)
            continue
        prefix = m.group(1).upper()
        digits = m.group(2)
        if prefix not in grid_letters or len(digits) % 2 != 0:
            lats.append(None)
            lons.append(None)
            continue
        half = len(digits) // 2
        e_offset = int(digits[:half]) * (10 ** (5 - half))
        n_offset = int(digits[half:]) * (10 ** (5 - half))
        gx, gy = grid_letters[prefix]
        easting = gx * 100_000 + e_offset
        northing = gy * 100_000 + n_offset
        lat = 49.0 + (northing / 111_000)
        lon = -8.0 + (easting / (111_000 * 0.6))
        lats.append(round(lat, 5))
        lons.append(round(lon, 5))

    return (
        pl.Series("lat_approx", lats, dtype=pl.Float64),
        pl.Series("lon_approx", lons, dtype=pl.Float64),
    )


def fetch_pollution_incidents() -> pl.DataFrame:
    print("\n=== Pollution Incidents (NIRS2 Cat 1 & 2) ===")

    zip_path = TEMP_DIR / "pollution_incidents.zip"
    extract_dir = TEMP_DIR / "pollution_incidents"

    _download(POLLUTION_ZIP_URL, zip_path)
    _extract_zip(zip_path, extract_dir)

    incidents_csv = extract_dir / "EP_Incidents_Nirs2.csv"
    pollutants_csv = extract_dir / "EP_Pollutants_Nirs2.csv"

    incidents = pl.read_csv(incidents_csv, infer_schema_length=5000)
    pollutants = pl.read_csv(pollutants_csv, infer_schema_length=5000)

    raw_count = len(incidents)
    print(f"  Raw incident records: {raw_count:,}")
    print(f"  Raw pollutant records: {len(pollutants):,}")

    # --- Step 1: Keep only incidents with water impact (Cat 1, 2, or 3) ---
    water_impact = incidents.filter(
        pl.col("EIL_WATER").is_in([
            "Category 1 (Major)",
            "Category 2 (Significant)",
            "Category 3 (Minor)",
        ])
    )
    print(f"  After water-impact filter: {len(water_impact):,}")

    # --- Step 2: Join with pollutants and apply scope filter ---
    pollutants_relevant = pollutants.filter(
        pl.col("POLL_TYPE").is_in(WATER_RELEVANT_POLL_TYPES)
        | pl.col("POLLUTANT").is_in(WATER_RELEVANT_POLLUTANTS)
    ).filter(
        ~pl.col("POLLUTANT").is_in(OUT_OF_SCOPE_POLLUTANTS)
    )

    relevant_ids = pollutants_relevant.select("NOT_ID").unique()
    water_relevant = water_impact.join(relevant_ids, on="NOT_ID", how="inner")
    print(f"  After scope filter (pollutant match): {len(water_relevant):,}")

    # Also keep any incident with water Cat 1 even if pollutant isn't in our list
    water_cat1 = water_impact.filter(
        pl.col("EIL_WATER") == "Category 1 (Major)"
    )
    water_relevant = pl.concat([water_relevant, water_cat1]).unique(subset=["NOT_ID"])
    print(f"  After adding all Cat 1 water incidents: {len(water_relevant):,}")

    # --- Step 3: Attach best pollutant info per incident ---
    best_pollutant = (
        pollutants
        .join(water_relevant.select("NOT_ID").unique(), on="NOT_ID", how="inner")
        .group_by("NOT_ID")
        .agg([
            pl.col("POLL_TYPE").first().alias("poll_type"),
            pl.col("POLLUTANT").first().alias("pollutant"),
            pl.concat_str(pl.col("POLLUTANT"), separator="; ").alias("all_pollutants"),
        ])
    )
    df = water_relevant.join(best_pollutant, on="NOT_ID", how="left")

    # --- Step 4: Parse date ---
    df = df.with_columns(
        pl.col("NOT_DATE")
        .str.strptime(pl.Datetime, "%d/%m/%Y %H:%M:%S", strict=False)
        .cast(pl.Date)
        .alias("incident_date")
    )

    # --- Step 5: Convert grid ref to approximate lat/lon ---
    lat_series, lon_series = _parse_ngr_to_latlon(df["NGR_CONF"])
    df = df.with_columns([lat_series, lon_series])

    # Also use X_CONF/Y_CONF (OS easting/northing) as a backup
    df = df.with_columns([
        pl.col("X_CONF").cast(pl.Float64, strict=False).alias("easting"),
        pl.col("Y_CONF").cast(pl.Float64, strict=False).alias("northing"),
    ])

    # Drop rows missing both coordinates
    before_geo = len(df)
    df = df.filter(
        pl.col("lat_approx").is_not_null()
        | (pl.col("easting").is_not_null() & pl.col("northing").is_not_null())
    )
    print(f"  Dropped {before_geo - len(df)} rows with no usable coordinates")

    # --- Step 6: Deduplicate ---
    # Round coordinates to ~100m grid for grouping
    df = df.with_columns([
        (pl.col("easting") / 100).round(0).alias("_e_grid"),
        (pl.col("northing") / 100).round(0).alias("_n_grid"),
    ])

    before_dedup = len(df)
    df = (
        df.group_by(["incident_date", "_e_grid", "_n_grid", "poll_type"])
        .agg([
            pl.col("NOT_ID").first(),
            pl.col("NOT_DATE").first(),
            pl.col("REGION_WM").first(),
            pl.col("AREA_WM").first(),
            pl.col("COUNTY").first(),
            pl.col("DISTRICT").first(),
            pl.col("NGR_CONF").first(),
            pl.col("easting").first(),
            pl.col("northing").first(),
            pl.col("lat_approx").first(),
            pl.col("lon_approx").first(),
            pl.col("EIL_WATER").first(),
            pl.col("EIL_LAND").first(),
            pl.col("EIL_AIR").first(),
            pl.col("pollutant").first(),
            pl.col("all_pollutants").first(),
            pl.len().alias("raw_report_count"),
        ])
    )
    print(f"  Deduplicated: {before_dedup:,} → {len(df):,} (removed {before_dedup - len(df):,} duplicates)")

    # --- Step 7: Clean up and select final columns ---
    df = df.select([
        pl.col("NOT_ID").alias("incident_id"),
        "incident_date",
        pl.col("REGION_WM").alias("region"),
        pl.col("AREA_WM").alias("area"),
        pl.col("COUNTY").alias("county"),
        pl.col("DISTRICT").alias("district"),
        pl.col("NGR_CONF").alias("grid_ref"),
        "easting",
        "northing",
        "lat_approx",
        "lon_approx",
        pl.col("EIL_WATER").alias("water_impact"),
        pl.col("EIL_LAND").alias("land_impact"),
        pl.col("EIL_AIR").alias("air_impact"),
        pl.col("poll_type").alias("pollutant_type"),
        pl.col("pollutant").alias("primary_pollutant"),
        "all_pollutants",
        "raw_report_count",
    ]).sort("incident_date", descending=True)

    discarded = raw_count - len(df)
    print(f"\n  Summary: {raw_count:,} raw → {discarded:,} discarded → {len(df):,} final records")

    return df


# ---------------------------------------------------------------------------
# 2. EDM Storm Overflow / Sewage Spills
# ---------------------------------------------------------------------------

def _normalise_edm_columns(col: str) -> str:
    """Normalise messy EDM column headers to clean snake_case."""
    col = col.strip()
    col = re.sub(r"\s*\(.*?\)", "", col)
    col = re.sub(r"\s*\[.*?\]", "", col)
    col = col.strip().lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = col.strip("_")
    return col


def _parse_edm_ngr(ngr_series: pl.Series) -> tuple[pl.Series, pl.Series]:
    """Extract approximate lat/lon from EDM grid references."""
    return _parse_ngr_to_latlon(ngr_series)


EDM_TARGET_COLUMNS = {
    "unique_id": ["unique id", "unique_id"],
    "water_company": ["water company name", "water_company_name", "company name"],
    "site_name": ["site name"],
    "permit_ref": ["ea permit ref", "permit ref", "ea_permit_ref"],
    "asset_type": ["storm discharge asset type", "asset type", "storm_discharge_asset"],
    "outlet_ngr": ["outlet discharge ngr", "ngr"],
    "waterbody_id": ["wfd waterbody id", "waterbody_id"],
    "waterbody_name": ["wfd waterbody catchment", "catchment name"],
    "receiving_water": ["receiving water", "receiving environment"],
    "spill_count": ["counted spills", "spill count"],
    "total_duration": ["total duration"],
}


def _match_col(target_patterns: list[str], raw_columns: list[str]) -> str | None:
    """Find the first raw column whose lowered name contains any pattern."""
    for col in raw_columns:
        low = col.lower()
        for pat in target_patterns:
            if pat in low:
                return col
    return None


def _standardise_edm_sheet(df: pl.DataFrame, year: int, sheet_name: str) -> pl.DataFrame | None:
    """Map raw XLSX columns to the standard EDM schema. Returns None if key columns are missing."""
    raw_cols = df.columns
    mapping: dict[str, str] = {}

    for target, patterns in EDM_TARGET_COLUMNS.items():
        found = _match_col(patterns, raw_cols)
        if found:
            mapping[target] = found

    if "outlet_ngr" not in mapping:
        return None

    select_exprs = [pl.col(src).cast(pl.Utf8).alias(tgt) for tgt, src in mapping.items()]
    select_exprs.append(pl.lit(year).cast(pl.Int64).alias("reporting_year"))

    if "water_company" not in mapping:
        company = sheet_name.replace(str(year), "").strip()
        select_exprs.append(pl.lit(company).alias("water_company"))

    return df.select(select_exprs)


def _detect_header_row(xlsx_path: str, sheet_name: str) -> int:
    """Find the header row by scanning for known EDM header keywords."""
    import fastexcel

    reader = fastexcel.read_excel(xlsx_path)
    sheet = reader.load_sheet(sheet_name, header_row=None, dtypes="string")
    df = pl.from_arrow(sheet.to_arrow())

    markers = ["unique id", "water company", "site name", "permit ref", "ngr"]
    for row_idx in range(min(10, len(df))):
        row_vals = " ".join(
            str(df[row_idx, c]).lower() for c in range(min(15, df.width))
        )
        matches = sum(1 for m in markers if m in row_vals)
        if matches >= 3:
            return row_idx
    return 1


def _read_edm_xlsx(xlsx_path: Path, year: int) -> pl.DataFrame:
    """Read all company sheets from an EDM XLSX, standardising to a common schema."""
    import fastexcel

    reader = fastexcel.read_excel(str(xlsx_path))
    frames = []

    data_sheets = [s for s in reader.sheet_names if "summary" not in s.lower()]
    if not data_sheets:
        return pl.DataFrame()

    header_row = _detect_header_row(str(xlsx_path), data_sheets[0])

    for sheet_name in data_sheets:
        try:
            sheet = reader.load_sheet(sheet_name, header_row=header_row, dtypes="string")
            df = pl.from_arrow(sheet.to_arrow())
        except Exception:
            continue

        if len(df) < 3:
            continue

        std = _standardise_edm_sheet(df, year, sheet_name)
        if std is not None and len(std) > 0:
            frames.append(std)

    if not frames:
        return pl.DataFrame()

    combined = pl.concat(frames, how="diagonal_relaxed")
    print(f"  {year}: {len(combined):,} records from {len(frames)} company sheets")
    return combined


def fetch_edm_data() -> pl.DataFrame:
    print("\n=== EDM Storm Overflow Sewage Spills ===")

    all_frames = []

    for year in EDM_YEARS:
        filename = f"EDM_{year}_Storm_Overflow_Annual_Return.zip"
        url = EDM_BASE_URL + filename.replace(" ", "%20")
        zip_path = TEMP_DIR / f"edm_{year}.zip"
        extract_dir = TEMP_DIR / f"edm_{year}"

        try:
            _download(url, zip_path)
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            print(f"  WARNING: Could not download {year} data: {e}")
            continue

        _extract_zip(zip_path, extract_dir)

        xlsx_files = list(extract_dir.rglob("*all water and sewerage companies*.xlsx"))
        if not xlsx_files:
            xlsx_files = list(extract_dir.rglob("*.xlsx"))
            xlsx_files = [f for f in xlsx_files if "summary" not in f.name.lower()]

        if not xlsx_files:
            print(f"  WARNING: No XLSX data file found for {year}")
            continue

        xlsx_path = xlsx_files[0]
        print(f"  Reading {xlsx_path.name} ...")

        try:
            year_df = _read_edm_xlsx(xlsx_path, year)
            if len(year_df) > 0:
                all_frames.append(year_df)
        except Exception as e:
            print(f"  ERROR: Failed to read {year} data: {e}")
            continue

    if not all_frames:
        print("  ERROR: No EDM data loaded!")
        return pl.DataFrame()

    df = pl.concat(all_frames, how="diagonal_relaxed")
    raw_count = len(df)
    print(f"\n  Total raw EDM records across all years: {raw_count:,}")
    print(f"  Columns: {df.columns}")

    # --- Parse NGR to lat/lon ---
    lat_s, lon_s = _parse_edm_ngr(df["outlet_ngr"])
    df = df.with_columns([lat_s, lon_s])

    # --- Drop rows with no location ---
    before_geo = len(df)
    df = df.filter(pl.col("lat_approx").is_not_null())
    print(f"  Dropped {before_geo - len(df)} rows with no parseable grid reference")

    # --- Cast spill count to numeric ---
    if "spill_count" in df.columns:
        df = df.with_columns(
            pl.col("spill_count").cast(pl.Float64, strict=False)
        )

    # --- Deduplicate: same site + same year = one record ---
    # Use unique_id + year when available; fall back to permit_ref + outlet_ngr + year
    before_dedup = len(df)
    if "spill_count" in df.columns:
        df = df.sort("spill_count", descending=True, nulls_last=True)
    has_id = df.filter(pl.col("unique_id").is_not_null())
    no_id = df.filter(pl.col("unique_id").is_null())
    if len(has_id) > 0:
        has_id = has_id.unique(subset=["unique_id", "reporting_year"], keep="first")
    if len(no_id) > 0:
        fallback_cols = [c for c in ["permit_ref", "outlet_ngr", "reporting_year"] if c in no_id.columns]
        if fallback_cols:
            no_id = no_id.unique(subset=fallback_cols, keep="first")
    df = pl.concat([has_id, no_id], how="diagonal_relaxed")
    print(f"  Deduplicated: {before_dedup:,} → {len(df):,}")

    # --- Filter: only keep overflows that actually spilled ---
    if "spill_count" in df.columns:
        before_spill = len(df)
        df = df.filter(
            (pl.col("spill_count") > 0) | pl.col("spill_count").is_null()
        )
        print(f"  After removing zero-spill entries: {before_spill:,} → {len(df):,}")

    sort_cols = ["reporting_year"] + (["water_company"] if "water_company" in df.columns else [])
    df = df.sort(sort_cols, descending=[True] + [False] * (len(sort_cols) - 1))

    discarded = raw_count - len(df)
    print(f"\n  Summary: {raw_count:,} raw → {discarded:,} discarded → {len(df):,} final records")

    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # --- Pollution Incidents ---
    pi_df = fetch_pollution_incidents()
    pi_path = RAW_DIR / "ea_pollution_incidents_cleaned.parquet"
    pi_df.write_parquet(pi_path)
    print(f"\n  Saved {len(pi_df):,} pollution incident records → {pi_path}")

    # --- EDM Sewage Spills ---
    edm_df = fetch_edm_data()
    if len(edm_df) > 0:
        edm_path = RAW_DIR / "ea_edm_sewage_spills_cleaned.parquet"
        edm_df.write_parquet(edm_path)
        print(f"\n  Saved {len(edm_df):,} EDM sewage spill records → {edm_path}")

    # --- Cleanup temp ---
    print("\n  Cleaning up temp files ...")
    shutil.rmtree(TEMP_DIR, ignore_errors=True)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
