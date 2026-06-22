"""
Phase 2 – Spatial Join & Aggregation
Joins EA pollution incidents and EDM sewage spill data to River Signal
monitoring sites using a 2 km radius, then aggregates per site.
"""

import json
import os
import re
from math import radians, sin, cos, sqrt, atan2, pi

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANKED_FEED = os.path.join(BASE_DIR, "data", "output", "ranked_feed.json")
POLLUTION_PQ = os.path.join(BASE_DIR, "data", "raw", "ea_pollution_incidents_cleaned.parquet")
EDM_PQ = os.path.join(BASE_DIR, "data", "raw", "ea_edm_sewage_spills_cleaned.parquet")
OUT_DIR = os.path.join(BASE_DIR, "data", "processed")
OUT_PARQUET = os.path.join(OUT_DIR, "site_incident_summary.parquet")
OUT_JSON = os.path.join(OUT_DIR, "site_incident_summary.json")

RADIUS_M = 2000  # 2 km

# ---------------------------------------------------------------------------
# Haversine distance (metres) between two (lat, lon) points
# ---------------------------------------------------------------------------
EARTH_R = 6_371_000  # mean Earth radius in metres


def haversine_vec(lat1, lon1, lat2, lon2):
    """Vectorised Haversine returning distance in metres."""
    lat1, lon1, lat2, lon2 = (np.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return EARTH_R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


# ---------------------------------------------------------------------------
# OSGB36 Easting/Northing -> approximate WGS84 lat/lon
# Uses Helmert-style linear approximation good to ~5 m for England/Wales.
# ---------------------------------------------------------------------------
def osgb_to_latlon(easting, northing):
    """Convert OSGB36 easting/northing to approximate WGS84 lat/lon."""
    E0, N0 = 400_000, -100_000
    F0 = 0.9996012717
    phi0 = 49 * pi / 180
    lam0 = -2 * pi / 180
    a = 6_377_563.396
    b = 6_356_256.909
    e2 = 1 - (b * b) / (a * a)

    n = (a - b) / (a + b)
    n2, n3 = n * n, n * n * n

    phi = phi0
    for _ in range(10):
        M = b * F0 * (
            (1 + n + 1.25 * n2 + 1.25 * n3) * (phi - phi0)
            - (3 * n + 3 * n2 + 21 / 8 * n3) * np.sin(phi - phi0) * np.cos(phi + phi0)
            + (15 / 8 * n2 + 15 / 8 * n3) * np.sin(2 * (phi - phi0)) * np.cos(2 * (phi + phi0))
            - (35 / 24 * n3) * np.sin(3 * (phi - phi0)) * np.cos(3 * (phi + phi0))
        )
        phi = (northing - N0 - M) / (a * F0) + phi

    sin_phi = np.sin(phi)
    cos_phi = np.cos(phi)
    tan_phi = np.tan(phi)
    nu = a * F0 / np.sqrt(1 - e2 * sin_phi ** 2)
    rho = a * F0 * (1 - e2) / (1 - e2 * sin_phi ** 2) ** 1.5
    eta2 = nu / rho - 1

    dE = easting - E0
    VII = tan_phi / (2 * rho * nu)
    VIII = tan_phi / (24 * rho * nu ** 3) * (5 + 3 * tan_phi ** 2 + eta2 - 9 * tan_phi ** 2 * eta2)
    IX = tan_phi / (720 * rho * nu ** 5) * (61 + 90 * tan_phi ** 2 + 45 * tan_phi ** 4)
    X = 1 / (cos_phi * nu)
    XI = 1 / (6 * cos_phi * nu ** 3) * (nu / rho + 2 * tan_phi ** 2)
    XII = 1 / (120 * cos_phi * nu ** 5) * (5 + 28 * tan_phi ** 2 + 24 * tan_phi ** 4)

    lat = phi - VII * dE ** 2 + VIII * dE ** 4 - IX * dE ** 6
    lon = lam0 + X * dE - XI * dE ** 3 + XII * dE ** 5

    return np.degrees(lat), np.degrees(lon)


# ---------------------------------------------------------------------------
# Parse messy total_duration column -> hours (float)
# ---------------------------------------------------------------------------
def parse_duration_hours(series: pd.Series) -> pd.Series:
    """Convert mixed-format duration column to numeric hours."""
    result = pd.to_numeric(series, errors="coerce")

    # HH:MM:SS or HHH:MM:SS strings -> hours
    hms_mask = series.str.match(r"^\d+:\d{2}:\d{2}$", na=False)
    if hms_mask.any():
        parts = series[hms_mask].str.split(":", expand=True).astype(float)
        result[hms_mask] = parts[0] + parts[1] / 60 + parts[2] / 3600

    # Excel 1899-12-31 datetime artifacts -> extract time portion as hours
    dt_mask = series.str.contains("1899", na=False)
    if dt_mask.any():
        ts = pd.to_datetime(series[dt_mask], errors="coerce")
        result[dt_mask] = ts.dt.hour + ts.dt.minute / 60 + ts.dt.second / 3600

    return result


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
def load_sites() -> pd.DataFrame:
    with open(RANKED_FEED, "r", encoding="utf-8") as f:
        feed = json.load(f)
    sites = pd.DataFrame(feed["feed"])[["site_id", "lat", "lon"]]
    print(f"Loaded {len(sites)} River Signal sites from ranked_feed.json")
    return sites


def load_pollution() -> pd.DataFrame:
    df = pd.read_parquet(POLLUTION_PQ)
    # Fill missing lat/lon from easting/northing via OSGB conversion
    missing = df["lat_approx"].isna()
    if missing.any():
        lat_conv, lon_conv = osgb_to_latlon(
            df.loc[missing, "easting"].values.astype(float),
            df.loc[missing, "northing"].values.astype(float),
        )
        df.loc[missing, "lat_approx"] = lat_conv
        df.loc[missing, "lon_approx"] = lon_conv
        print(f"  Converted {missing.sum()} pollution incidents from OSGB -> lat/lon")
    remaining_null = df["lat_approx"].isna().sum()
    if remaining_null:
        print(f"  WARNING: {remaining_null} pollution incidents still lack coordinates — dropped")
        df = df.dropna(subset=["lat_approx", "lon_approx"])
    print(f"Loaded {len(df)} pollution incidents")
    return df


def load_edm() -> pd.DataFrame:
    df = pd.read_parquet(EDM_PQ)
    df = df.dropna(subset=["lat_approx", "lon_approx"])
    df["duration_hours"] = parse_duration_hours(df["total_duration"])
    print(f"Loaded {len(df)} EDM sewage spill records")
    valid_dur = df["duration_hours"].notna().sum()
    print(f"  {valid_dur} records have parseable duration "
          f"(total = {df['duration_hours'].sum():,.1f} hrs)")
    return df


# ---------------------------------------------------------------------------
# Spatial join: for each site, find incidents within RADIUS_M
# ---------------------------------------------------------------------------
def spatial_join(sites: pd.DataFrame, incidents: pd.DataFrame,
                 inc_lat_col: str, inc_lon_col: str) -> dict:
    """Return dict mapping site_id -> list of incident row indices within radius."""
    site_lats = sites["lat"].values
    site_lons = sites["lon"].values
    site_ids = sites["site_id"].values

    inc_lats = incidents[inc_lat_col].values.astype(float)
    inc_lons = incidents[inc_lon_col].values.astype(float)

    matches: dict[str, list[int]] = {sid: [] for sid in site_ids}

    # Pre-filter bounding box: 2 km ≈ 0.018° lat, generous lon margin
    LAT_TOL = 0.02
    LON_TOL = 0.04  # generous for UK latitudes

    n_sites = len(site_ids)
    report_every = max(1, n_sites // 10)

    for i in range(n_sites):
        if i % report_every == 0:
            print(f"  Processing site {i + 1}/{n_sites} …")
        slat, slon = site_lats[i], site_lons[i]

        # Bounding-box pre-filter
        bbox_mask = (
            (np.abs(inc_lats - slat) <= LAT_TOL) &
            (np.abs(inc_lons - slon) <= LON_TOL)
        )
        candidates = np.where(bbox_mask)[0]
        if len(candidates) == 0:
            continue

        dists = haversine_vec(slat, slon, inc_lats[candidates], inc_lons[candidates])
        within = candidates[dists <= RADIUS_M]
        if len(within):
            matches[site_ids[i]] = within.tolist()

    return matches


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def aggregate_pollution(sites: pd.DataFrame, pollution: pd.DataFrame,
                        matches: dict) -> pd.DataFrame:
    rows = []
    for sid in sites["site_id"]:
        idxs = matches.get(sid, [])
        if idxs:
            subset = pollution.iloc[idxs]
            total = len(subset)
            most_recent = pd.to_datetime(subset["incident_date"], errors="coerce").max()
            most_recent = str(most_recent.date()) if pd.notna(most_recent) else None
            cause_col = "pollutant_type" if "pollutant_type" in subset.columns else "primary_pollutant"
            primary_cause = subset[cause_col].mode().iloc[0] if not subset[cause_col].mode().empty else None
        else:
            total = 0
            most_recent = None
            primary_cause = None
        rows.append({
            "site_id": sid,
            "total_pollution_incidents": total,
            "most_recent_pollution_date": most_recent,
            "primary_pollution_cause": primary_cause,
        })
    return pd.DataFrame(rows)


def aggregate_edm(sites: pd.DataFrame, edm: pd.DataFrame,
                  matches: dict) -> pd.DataFrame:
    rows = []
    for sid in sites["site_id"]:
        idxs = matches.get(sid, [])
        if idxs:
            subset = edm.iloc[idxs]
            total_spills = int(subset["spill_count"].sum()) if "spill_count" in subset.columns else len(subset)
            total_records = len(subset)
            total_hours = float(subset["duration_hours"].sum()) if "duration_hours" in subset.columns else 0.0
            if np.isnan(total_hours):
                total_hours = 0.0
            most_recent_col = "reporting_year"
            most_recent = str(int(subset[most_recent_col].max())) if most_recent_col in subset.columns else None
        else:
            total_spills = 0
            total_records = 0
            total_hours = 0.0
            most_recent = None
        rows.append({
            "site_id": sid,
            "total_edm_spills": total_records,
            "total_edm_spill_events": total_spills,
            "total_spill_hours": round(total_hours, 2),
            "most_recent_spill_date": most_recent,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("PHASE 2: Spatial Join & Aggregation")
    print("=" * 60)

    sites = load_sites()
    pollution = load_pollution()
    edm = load_edm()

    # --- Spatial join: Pollution incidents ---
    print("\n--- Spatial join: Pollution Incidents (2 km radius) ---")
    poll_matches = spatial_join(sites, pollution, "lat_approx", "lon_approx")

    # --- Spatial join: EDM spills ---
    print("\n--- Spatial join: EDM Sewage Spills (2 km radius) ---")
    edm_matches = spatial_join(sites, edm, "lat_approx", "lon_approx")

    # --- Aggregate ---
    print("\n--- Aggregating per site ---")
    poll_agg = aggregate_pollution(sites, pollution, poll_matches)
    edm_agg = aggregate_edm(sites, edm, edm_matches)

    merged = poll_agg.merge(edm_agg, on="site_id", how="outer")
    merged["has_any_incidents"] = (
        (merged["total_pollution_incidents"] > 0) | (merged["total_edm_spills"] > 0)
    )
    merged["total_all_incidents"] = (
        merged["total_pollution_incidents"] + merged["total_edm_spills"]
    )

    # --- Summary stats ---
    sites_with = (merged["has_any_incidents"]).sum()
    sites_without = len(merged) - sites_with
    total_spill_hours = merged["total_spill_hours"].sum()

    print(f"\n{'=' * 60}")
    print(f"RESULTS")
    print(f"{'=' * 60}")
    print(f"Total River Signal sites:       {len(merged):,}")
    print(f"Sites WITH >=1 incident (2 km):  {sites_with:,}")
    print(f"Sites with ZERO incidents:      {sites_without:,}")
    print(f"Total pollution incidents matched: {merged['total_pollution_incidents'].sum():,}")
    print(f"Total EDM spill records matched:  {merged['total_edm_spills'].sum():,}")
    print(f"Total spill hours (all sites):  {total_spill_hours:,.2f}")
    print(f"{'=' * 60}")

    # --- Save ---
    os.makedirs(OUT_DIR, exist_ok=True)
    merged.to_parquet(OUT_PARQUET, index=False)
    print(f"\nSaved Parquet -> {OUT_PARQUET}")

    records = merged.to_dict(orient="records")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)
    print(f"Saved JSON   -> {OUT_JSON}")

    # Top 10 most-affected sites
    top10 = merged.nlargest(10, "total_all_incidents")[
        ["site_id", "total_pollution_incidents", "total_edm_spills", "total_spill_hours", "total_all_incidents"]
    ]
    print(f"\nTop 10 most-affected sites:")
    print(top10.to_string(index=False))


if __name__ == "__main__":
    main()
