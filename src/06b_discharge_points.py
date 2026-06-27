"""
Phase 3b – Regulated Discharge Points
Fetches consented discharge data from the EA Access database, filters to
sewage/industrial categories, converts OS Grid References to lat/lon,
and performs a 2km spatial join against River Signal monitoring sites.
"""

import json
import os
import re
from math import pi

import numpy as np
import pandas as pd
import pyodbc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANKED_FEED = os.path.join(BASE_DIR, "data", "output", "ranked_feed.json")
ACCDB_PATH = os.path.join(
    BASE_DIR, "data", "raw",
    "Consented Discharges to Controlled Waters with Conditions.accdb",
)
OUT_DIR = os.path.join(BASE_DIR, "data", "processed")
OUT_JSON = os.path.join(OUT_DIR, "site_discharge_points.json")

RADIUS_M = 2000
EARTH_R = 6_371_000

SEWAGE_TYPES = {"SA", "SB", "SC", "SD", "SE", "UA", "UB", "UC", "UD", "UE"}
STORM_OVERFLOW_TYPES = {"SB", "SC", "UB", "UC"}
INDUSTRIAL_TYPES = {"TA", "TB", "TC", "TD", "TE", "TF", "TG"}
ALL_TARGET_TYPES = SEWAGE_TYPES | INDUSTRIAL_TYPES


# ---------------------------------------------------------------------------
# OS Grid Reference -> Easting/Northing -> Lat/Lon
# ---------------------------------------------------------------------------
_NGR_LETTERS = {
    "SV": (0, 0), "SW": (1, 0), "SX": (2, 0), "SY": (3, 0), "SZ": (4, 0), "TV": (5, 0), "TW": (6, 0),
    "SQ": (0, 1), "SR": (1, 1), "SS": (2, 1), "ST": (3, 1), "SU": (4, 1), "TQ": (5, 1), "TR": (6, 1),
    "SL": (0, 2), "SM": (1, 2), "SN": (2, 2), "SO": (3, 2), "SP": (4, 2), "TL": (5, 2), "TM": (6, 2),
    "SF": (0, 3), "SG": (1, 3), "SH": (2, 3), "SJ": (3, 3), "SK": (4, 3), "TF": (5, 3), "TG": (6, 3),
    "SA": (0, 4), "SB": (1, 4), "SC": (2, 4), "SD": (3, 4), "SE": (4, 4), "TA": (5, 4), "TB": (6, 4),
    "HV": (0, 5), "HW": (1, 5), "HX": (2, 5), "HY": (3, 5), "HZ": (4, 5), "NV": (5, 5), "NW": (6, 5),
    "HQ": (0, 6), "HR": (1, 6), "HS": (2, 6), "HT": (3, 6), "HU": (4, 6), "NQ": (5, 6), "NR": (6, 6),
    "HL": (0, 7), "HM": (1, 7), "HN": (2, 7), "HO": (3, 7), "HP": (4, 7), "NL": (5, 7), "NM": (6, 7),
    "NA": (0, 8), "NB": (1, 8), "NC": (2, 8), "ND": (3, 8), "NE": (4, 8),
    "NF": (0, 9), "NG": (1, 9), "NH": (2, 9), "NJ": (3, 9), "NK": (4, 9),
    "NY": (3, 5), "NZ": (4, 5), "NT": (3, 6), "NU": (4, 6), "NO": (3, 7), "NP": (4, 7),
    "NS": (2, 6), "NN": (2, 7), "NX": (2, 5),
    "OV": (7, 5),
}


def ngr_to_easting_northing(ngr: str):
    """Parse OS National Grid Reference string to easting/northing."""
    if not ngr or not isinstance(ngr, str):
        return None, None
    ngr = ngr.strip().replace(" ", "").upper()
    if len(ngr) < 4:
        return None, None
    letters = ngr[:2]
    digits = ngr[2:]
    if letters not in _NGR_LETTERS:
        return None, None
    if not digits.isdigit() or len(digits) % 2 != 0:
        return None, None
    half = len(digits) // 2
    e_part = digits[:half]
    n_part = digits[half:]
    grid_e, grid_n = _NGR_LETTERS[letters]
    easting = grid_e * 100_000 + int(e_part) * (10 ** (5 - half))
    northing = grid_n * 100_000 + int(n_part) * (10 ** (5 - half))
    return easting, northing


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


def haversine_vec(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return EARTH_R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def load_sites() -> pd.DataFrame:
    with open(RANKED_FEED, "r", encoding="utf-8") as f:
        feed = json.load(f)
    sites = pd.DataFrame(feed["feed"])[["site_id", "lat", "lon"]]
    print(f"Loaded {len(sites)} sites")
    return sites


def load_discharges() -> pd.DataFrame:
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={ACCDB_PATH}"
    )
    conn = pyodbc.connect(conn_str)
    query = """
        SELECT COMPANY_NAME, DISCHARGE_SITE_NAME, DISCHARGE_NGR,
               EFFLUENT_TYPE, EFF_TYPE_DESCRIPTION,
               OUTLET_GRID_REF, EFFLUENT_GRID_REF,
               RECEIVING_WATER, EA_REGION, PERMIT_NUMBER
        FROM [consents_active]
    """
    df = pd.read_sql(query, conn)
    conn.close()
    print(f"Loaded {len(df)} total active consents from Access DB")

    df = df[df["EFFLUENT_TYPE"].isin(ALL_TARGET_TYPES)].copy()
    print(f"Filtered to {len(df)} sewage/industrial discharge records")

    return df


def convert_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Convert OS Grid References to lat/lon coordinates."""
    grid_ref_col = "EFFLUENT_GRID_REF"
    fallback_col = "DISCHARGE_NGR"

    refs = df[grid_ref_col].fillna(df[fallback_col])
    eastings = []
    northings = []
    for ref in refs:
        e, n = ngr_to_easting_northing(ref)
        eastings.append(e)
        northings.append(n)

    df = df.copy()
    df["easting"] = eastings
    df["northing"] = northings

    valid = df["easting"].notna()
    print(f"  Parsed {valid.sum()}/{len(df)} grid references successfully")
    if (~valid).any():
        print(f"  WARNING: {(~valid).sum()} records had unparseable grid references — dropped")
        df = df[valid].copy()

    e_arr = df["easting"].values.astype(float)
    n_arr = df["northing"].values.astype(float)
    lats, lons = osgb_to_latlon(e_arr, n_arr)
    df["lat"] = lats
    df["lon"] = lons
    return df


def classify_discharge(eff_type: str) -> str:
    if eff_type in STORM_OVERFLOW_TYPES:
        return "storm_overflow"
    if eff_type in SEWAGE_TYPES:
        return "sewage_works"
    if eff_type in INDUSTRIAL_TYPES:
        return "industrial"
    return "other"


def deduplicate_discharges(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate by permit + location to avoid counting the same site multiple times."""
    before = len(df)
    df = df.drop_duplicates(subset=["PERMIT_NUMBER", "EFFLUENT_TYPE", "DISCHARGE_NGR"])
    after = len(df)
    if before != after:
        print(f"  Deduplicated: {before} -> {after} records")
    return df


def spatial_join(sites: pd.DataFrame, discharges: pd.DataFrame) -> dict:
    site_lats = sites["lat"].values
    site_lons = sites["lon"].values
    site_ids = sites["site_id"].values

    dis_lats = discharges["lat"].values.astype(float)
    dis_lons = discharges["lon"].values.astype(float)

    LAT_TOL = 0.02
    LON_TOL = 0.04

    matches: dict[str, list[int]] = {sid: [] for sid in site_ids}
    n_sites = len(site_ids)
    report_every = max(1, n_sites // 10)

    for i in range(n_sites):
        if i % report_every == 0:
            print(f"  Processing site {i + 1}/{n_sites} …")
        slat, slon = site_lats[i], site_lons[i]

        bbox_mask = (
            (np.abs(dis_lats - slat) <= LAT_TOL) &
            (np.abs(dis_lons - slon) <= LON_TOL)
        )
        candidates = np.where(bbox_mask)[0]
        if len(candidates) == 0:
            continue

        dists = haversine_vec(slat, slon, dis_lats[candidates], dis_lons[candidates])
        within = candidates[dists <= RADIUS_M]
        if len(within):
            matches[site_ids[i]] = within.tolist()

    return matches


def aggregate(sites: pd.DataFrame, discharges: pd.DataFrame, matches: dict) -> list[dict]:
    dis_lats = discharges["lat"].values
    dis_lons = discharges["lon"].values
    dis_types = discharges["discharge_category"].values
    dis_names = discharges["DISCHARGE_SITE_NAME"].values
    dis_eff_types = discharges["EFFLUENT_TYPE"].values

    records = []
    for _, site in sites.iterrows():
        sid = site["site_id"]
        slat, slon = site["lat"], site["lon"]
        idxs = matches.get(sid, [])

        if not idxs:
            records.append({
                "site_id": sid,
                "discharge_points": None,
            })
            continue

        subset_cats = dis_types[idxs]
        subset_names = dis_names[idxs]
        subset_lats = dis_lats[idxs]
        subset_lons = dis_lons[idxs]

        sewage_count = int(np.sum((subset_cats == "sewage_works")))
        storm_count = int(np.sum((subset_cats == "storm_overflow")))
        industrial_count = int(np.sum((subset_cats == "industrial")))
        total = len(idxs)

        dists = haversine_vec(slat, slon, subset_lats, subset_lons)

        nearest_sewage = None
        nearest_industrial = None

        sewage_mask = (subset_cats == "sewage_works") | (subset_cats == "storm_overflow")
        if sewage_mask.any():
            sewage_dists = dists[sewage_mask]
            sewage_names_sub = subset_names[sewage_mask]
            nearest_idx = np.argmin(sewage_dists)
            name = sewage_names_sub[nearest_idx]
            nearest_sewage = {
                "name": str(name) if name else "Unknown",
                "distance_m": int(round(sewage_dists[nearest_idx])),
            }

        industrial_mask = subset_cats == "industrial"
        if industrial_mask.any():
            ind_dists = dists[industrial_mask]
            ind_names_sub = subset_names[industrial_mask]
            nearest_idx = np.argmin(ind_dists)
            name = ind_names_sub[nearest_idx]
            nearest_industrial = {
                "name": str(name) if name else "Unknown",
                "distance_m": int(round(ind_dists[nearest_idx])),
            }

        records.append({
            "site_id": sid,
            "discharge_points": {
                "sewage_works_count": sewage_count,
                "storm_overflows_count": storm_count,
                "industrial_discharges_count": industrial_count,
                "total_discharge_points": total,
                "has_discharge_points": total > 0,
                "nearest_sewage_work": nearest_sewage,
                "nearest_industrial": nearest_industrial,
            },
        })

    return records


def main():
    print("=" * 60)
    print("PHASE 3b: Regulated Discharge Points")
    print("=" * 60)

    sites = load_sites()
    discharges = load_discharges()

    print("\n--- Converting coordinates ---")
    discharges = convert_coordinates(discharges)
    discharges["discharge_category"] = discharges["EFFLUENT_TYPE"].apply(classify_discharge)

    print("\n--- Deduplicating ---")
    discharges = deduplicate_discharges(discharges)

    cat_counts = discharges["discharge_category"].value_counts()
    print(f"\nDischarge categories:")
    for cat, count in cat_counts.items():
        print(f"  {cat}: {count:,}")

    print(f"\n--- Spatial join: Discharge points (2 km radius) ---")
    matches = spatial_join(sites, discharges)

    print(f"\n--- Aggregating per site ---")
    records = aggregate(sites, discharges, matches)

    with_points = sum(1 for r in records if r["discharge_points"] is not None)
    without_points = sum(1 for r in records if r["discharge_points"] is None)
    total_matched = sum(
        r["discharge_points"]["total_discharge_points"]
        for r in records if r["discharge_points"]
    )

    print(f"\nRESULTS:")
    print(f"  Sites with discharge points within 2km: {with_points:,}")
    print(f"  Sites without nearby discharge points: {without_points:,}")
    print(f"  Total site-discharge associations: {total_matched:,}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nSaved -> {OUT_JSON}")


if __name__ == "__main__":
    main()
