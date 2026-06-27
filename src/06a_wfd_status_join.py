"""
Phase 3a – WFD Status Spatial Join
Joins Water Framework Directive ecological/chemical classification status
to River Signal monitoring sites using point-in-polygon spatial join
against the Cycle 3 (2022) waterbody catchment polygons.
"""

import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANKED_FEED = os.path.join(BASE_DIR, "data", "output", "ranked_feed.json")
WFD_GPKG = os.path.join(
    BASE_DIR, "data", "raw",
    "Water_Framework_Directive_WFD_River_Water_Body_Catchments_Cycle_3_Classification_2022_Full_Resolution.gpkg",
)
OUT_DIR = os.path.join(BASE_DIR, "data", "processed")
OUT_JSON = os.path.join(OUT_DIR, "site_wfd_status.json")


def load_sites() -> gpd.GeoDataFrame:
    with open(RANKED_FEED, "r", encoding="utf-8") as f:
        feed = json.load(f)
    df = pd.DataFrame(feed["feed"])[["site_id", "lat", "lon"]]
    geometry = [Point(lon, lat) for lat, lon in zip(df["lat"], df["lon"])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    gdf = gdf.to_crs("EPSG:27700")
    print(f"Loaded {len(gdf)} sites, reprojected to OSGB (EPSG:27700)")
    return gdf


def load_wfd_polygons() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(WFD_GPKG)
    rivers = gdf[gdf["water_body_type"] == "River"].copy()
    rivers = rivers[[
        "water_body_id", "water_body_name",
        "overall_water_body_class", "ecological_class", "chemical_class",
        "geometry",
    ]]
    print(f"Loaded {len(rivers)} River waterbody polygons from GeoPackage")
    return rivers


def spatial_join_pip(sites: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Point-in-polygon spatial join."""
    joined = gpd.sjoin(sites, polygons, how="left", predicate="within")
    dupes = joined.index.duplicated(keep="first")
    if dupes.any():
        print(f"  Removed {dupes.sum()} duplicate matches (keeping first)")
        joined = joined[~dupes]
    matched = joined["water_body_id"].notna().sum()
    print(f"  Point-in-polygon matched {matched}/{len(sites)} sites")
    return joined


def nearest_fallback(
    joined: gpd.GeoDataFrame,
    sites: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """For unmatched sites, find the nearest polygon centroid and assign its status."""
    unmatched_mask = joined["water_body_id"].isna()
    n_unmatched = unmatched_mask.sum()
    if n_unmatched == 0:
        print("  All sites matched via point-in-polygon, no fallback needed")
        return joined

    print(f"  Attempting nearest-centroid fallback for {n_unmatched} unmatched sites")
    centroids = polygons.copy()
    centroids["centroid_geom"] = centroids.geometry.centroid
    centroids = centroids.set_geometry("centroid_geom")

    unmatched_sites = sites.loc[unmatched_mask]
    nearest = gpd.sjoin_nearest(
        unmatched_sites, centroids, how="left", distance_col="_dist_m",
    )
    dupes = nearest.index.duplicated(keep="first")
    if dupes.any():
        nearest = nearest[~dupes]

    max_dist = 10_000  # 10 km max for fallback
    too_far = nearest["_dist_m"] > max_dist
    if too_far.any():
        print(f"  {too_far.sum()} sites >10km from nearest polygon centroid — left as null")
        nearest.loc[too_far, ["water_body_id", "water_body_name",
                              "overall_water_body_class", "ecological_class",
                              "chemical_class"]] = None

    for col in ["water_body_id", "water_body_name", "overall_water_body_class",
                "ecological_class", "chemical_class"]:
        joined.loc[unmatched_mask, col] = nearest[col].values

    fallback_matched = joined.loc[unmatched_mask, "water_body_id"].notna().sum()
    print(f"  Nearest-centroid fallback matched {fallback_matched}/{n_unmatched} additional sites")
    return joined


def build_output(joined: gpd.GeoDataFrame) -> list[dict]:
    records = []
    for _, row in joined.iterrows():
        overall = row.get("overall_water_body_class")
        ecological = row.get("ecological_class")
        chemical = row.get("chemical_class")

        has_status = pd.notna(ecological) and ecological not in ("Not assessed",)
        if not has_status:
            records.append({"site_id": row["site_id"], "wfd_status": None})
            continue

        overall_clean = overall if pd.notna(overall) and overall != "Not assessed" else None
        chemical_clean = chemical if pd.notna(chemical) and chemical != "Does not require assessment" else None

        records.append({
            "site_id": row["site_id"],
            "wfd_status": {
                "overall_status": overall_clean,
                "ecological_status": ecological,
                "chemical_status": chemical_clean,
            },
        })
    return records


def main():
    print("=" * 60)
    print("PHASE 3a: WFD Status Spatial Join")
    print("=" * 60)

    sites = load_sites()
    polygons = load_wfd_polygons()

    print("\n--- Spatial join: Point-in-polygon ---")
    joined = spatial_join_pip(sites, polygons)

    print("\n--- Nearest-centroid fallback ---")
    joined = nearest_fallback(joined, sites, polygons)

    print("\n--- Building output ---")
    records = build_output(joined)

    with_status = sum(1 for r in records if r["wfd_status"] is not None)
    without_status = sum(1 for r in records if r["wfd_status"] is None)
    print(f"Sites with WFD status: {with_status}")
    print(f"Sites without WFD status: {without_status}")

    if with_status > 0:
        eco_counts = {}
        for r in records:
            if r["wfd_status"]:
                eco = r["wfd_status"]["ecological_status"]
                eco_counts[eco] = eco_counts.get(eco, 0) + 1
        print("\nEcological status distribution:")
        for status, count in sorted(eco_counts.items(), key=lambda x: -x[1]):
            print(f"  {status}: {count}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nSaved -> {OUT_JSON}")


if __name__ == "__main__":
    main()
