"""
Layer 3 - SCORE
===============
For each site, compute how anomalous its chemistry is relative to peers and
produce a national ranking by severity.

Input:  data/processed/site_fingerprints.parquet
Output: data/processed/scored_sites.parquet
"""

import pickle

import numpy as np
import polars as pl

from utils import load_config, get_path, setup_logger


log = setup_logger("03_score")


META_COLS = {
    "site_id",
    "site_label",
    "site_name",
    "lon",
    "lat",
    "region",
    "area",
    "sub_area",
    "site_type",
    "site_status",
    "water_body_id",
    "water_body_name",
    "water_body_type",
    "water_body_hmd",
    "wfd_type",
    "ecological_class",
    "chemical_class",
    "overall_water_body_class",
    "dist_to_wfd_m",
    "umap_x",
    "umap_y",
    "n_features_present",
}

NUMERIC_DTYPES = {
    pl.Float32,
    pl.Float64,
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
}


def _finite_std(values: np.ndarray) -> np.ndarray:
    std = np.nanstd(values, axis=0)
    std[~np.isfinite(std) | (std == 0)] = 1.0
    return std


def _global_reference(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.nanmean(X, axis=0), _finite_std(X)


def _valid_label(value: object) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, float) and np.isnan(value):
        return False
    return str(value).lower() != "nan"


def _clean_typology(value: object) -> str:
    """Return a stable typology label; missing values participate as Unknown."""
    if not _valid_label(value):
        return "Unknown"
    cleaned = str(value).strip()
    return cleaned if cleaned else "Unknown"


def _rms_z(z_scores: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        scores = np.sqrt(np.nanmean(z_scores**2, axis=1))
    return np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)


def _safe_print(value: object) -> None:
    """Print Polars previews safely on Windows consoles with cp1252 encoding."""
    print(str(value).encode("ascii", errors="replace").decode("ascii"))


def _load_model_features(proc_dir, df: pl.DataFrame) -> list[str]:
    model_path = proc_dir / "umap_model.pkl"
    if not model_path.exists():
        return []

    try:
        with open(model_path, "rb") as f:
            models = pickle.load(f)
        feature_cols = models.get("feature_cols", [])
    except Exception as exc:
        log.warning(f"Could not read UMAP model metadata: {exc}")
        return []

    return [c for c in feature_cols if c in df.columns]


def get_z_score_cols(df: pl.DataFrame) -> list[str]:
    """
    Dynamically detect determinand z-score columns.

    Layer 3 writes z-scores as "{full EA determinand name}_z", so hard-coding
    the 12 names would make the peer method brittle. We only accept numeric
    columns ending in "_z" to avoid accidental string/list columns.
    """
    return [
        name
        for name, dtype in zip(df.columns, df.dtypes)
        if name.endswith("_z") and dtype in NUMERIC_DTYPES
    ]


def get_feature_cols(df: pl.DataFrame, config: dict, proc_dir) -> list[str]:
    """
    Identify chemistry feature columns produced by layer 2.

    Prefer the feature list saved beside the UMAP model; otherwise use the
    configured panel, then fall back to numeric non-metadata columns.
    """
    from_model = _load_model_features(proc_dir, df)
    if from_model:
        return from_model

    panel_cols = [name for name in config["common_core_panel"].values() if name in df.columns]
    if panel_cols:
        return panel_cols

    numeric_types = {
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    }
    generated_suffixes = ("_z", "_rank", "_score", "_distance", "_overlap")
    feature_cols = []
    for name, dtype in zip(df.columns, df.dtypes):
        if name in META_COLS:
            continue
        if name.startswith(("is_", "flag_")) or name.endswith(generated_suffixes):
            continue
        if dtype in numeric_types:
            feature_cols.append(name)
    return feature_cols


def score_by_typology_peers(
    df: pl.DataFrame,
    feature_cols: list[str],
    min_group_size: int = 10,
) -> tuple[pl.DataFrame, np.ndarray]:
    """
    Score each site against its WFD typology group where possible.

    If WFD typology is missing or a group is too small, the site falls back to
    the global chemistry reference.
    """
    X = df.select(feature_cols).to_numpy().astype(float)
    global_mean, global_std = _global_reference(X)

    z_scores = np.zeros_like(X, dtype=float)
    peer_group_sizes = np.zeros(X.shape[0], dtype=int)
    reference_labels = np.array(["global"] * X.shape[0], dtype=object)

    if "wfd_type" not in df.columns:
        z_scores = (X - global_mean) / global_std
        df = df.with_columns(
            pl.lit("global").alias("score_reference"),
            pl.lit(int(X.shape[0])).alias("score_peer_group_size"),
        )
        return df, z_scores

    wfd_types = np.array(df["wfd_type"].to_list(), dtype=object)
    valid_types = sorted({t for t in wfd_types if _valid_label(t)})

    assigned = np.zeros(X.shape[0], dtype=bool)
    for wfd_type in valid_types:
        mask = wfd_types == wfd_type
        group_size = int(mask.sum())
        if group_size < min_group_size:
            continue

        group_X = X[mask]
        group_mean = np.nanmean(group_X, axis=0)
        group_std = _finite_std(group_X)
        z_scores[mask] = (X[mask] - group_mean) / group_std
        peer_group_sizes[mask] = group_size
        reference_labels[mask] = str(wfd_type)
        assigned[mask] = True

    fallback = ~assigned
    if fallback.any():
        z_scores[fallback] = (X[fallback] - global_mean) / global_std
        peer_group_sizes[fallback] = X.shape[0]

    df = df.with_columns(
        pl.Series("score_reference", reference_labels.tolist()),
        pl.Series("score_peer_group_size", peer_group_sizes),
    )
    return df, z_scores


def score_by_geographic_neighbours(
    df: pl.DataFrame,
    feature_cols: list[str],
    k: int = 20,
) -> pl.DataFrame:
    """
    Score each site against the k nearest sites by lat/lon.
    """
    from sklearn.neighbors import NearestNeighbors

    X = df.select(feature_cols).to_numpy().astype(float)
    coords = df.select(["lat", "lon"]).to_numpy().astype(float)
    valid = np.isfinite(coords).all(axis=1)

    geo_scores = np.full(X.shape[0], np.nan)
    geo_peer_distance_km = np.full(X.shape[0], np.nan)

    if valid.sum() < 3:
        log.warning("Not enough valid lat/lon values for geographic neighbour scoring")
        return df.with_columns(
            pl.Series("geo_anomaly_score", geo_scores),
            pl.Series("geo_peer_distance_km", geo_peer_distance_km),
            pl.lit(None).cast(pl.Int32).alias("geo_anomaly_rank"),
        )

    valid_idx = np.where(valid)[0]
    k_eff = min(k, valid_idx.size - 1)
    coords_rad = np.radians(coords[valid])
    nbrs = NearestNeighbors(n_neighbors=k_eff + 1, metric="haversine")
    nbrs.fit(coords_rad)
    distances, indices = nbrs.kneighbors(coords_rad)

    for local_i, global_i in enumerate(valid_idx):
        neighbour_global = valid_idx[indices[local_i, 1:]]
        neighbour_X = X[neighbour_global]
        mean = np.nanmean(neighbour_X, axis=0)
        std = _finite_std(neighbour_X)
        z = (X[global_i] - mean) / std
        geo_scores[global_i] = _rms_z(z.reshape(1, -1))[0]
        geo_peer_distance_km[global_i] = float(np.nanmean(distances[local_i, 1:]) * 6371.0088)

    ranks = pl.Series("geo_anomaly_score", geo_scores).rank(descending=True).cast(pl.Int32)
    return df.with_columns(
        pl.Series("geo_anomaly_score", geo_scores),
        pl.Series("geo_peer_distance_km", geo_peer_distance_km),
        ranks.alias("geo_anomaly_rank"),
    )


def add_embedding_peer_diagnostics(
    df: pl.DataFrame,
    feature_cols: list[str],
    k_broad: int = 20,
    k_final: int = 5,
) -> pl.DataFrame:
    """
    Notebook cells 54 and 56: compare 12D chemical neighbours with UMAP
    neighbours, and compute the hybrid UMAP-then-12D peer distance.
    """
    if "umap_x" not in df.columns or "umap_y" not in df.columns:
        return df

    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import StandardScaler

    X_raw = df.select(feature_cols).to_numpy().astype(float)
    X = StandardScaler(with_mean=True, with_std=True).fit_transform(X_raw)
    umap_coords = df.select(["umap_x", "umap_y"]).to_numpy().astype(float)
    valid = np.isfinite(X).all(axis=1) & np.isfinite(umap_coords).all(axis=1)

    n = X.shape[0]
    chem_knn_mean_distance = np.full(n, np.nan)
    umap_knn_mean_chem_distance = np.full(n, np.nan)
    hybrid_peer_mean_chem_distance = np.full(n, np.nan)
    peer_overlap_chem_umap = np.full(n, np.nan)

    if valid.sum() <= max(2, k_final):
        log.warning("Not enough complete rows for embedding peer diagnostics")
        return df

    valid_idx = np.where(valid)[0]
    Xv = X[valid]
    Uv = umap_coords[valid]

    k_chem = min(k_final, len(valid_idx) - 1)
    k_umap = min(k_broad, len(valid_idx) - 1)

    chem_nn = NearestNeighbors(n_neighbors=k_chem + 1, metric="euclidean").fit(Xv)
    _, chem_ind = chem_nn.kneighbors(Xv)

    umap_nn_final = NearestNeighbors(n_neighbors=k_chem + 1, metric="euclidean").fit(Uv)
    _, umap_ind_final = umap_nn_final.kneighbors(Uv)

    umap_nn_broad = NearestNeighbors(n_neighbors=k_umap + 1, metric="euclidean").fit(Uv)
    _, umap_ind_broad = umap_nn_broad.kneighbors(Uv)

    for local_i, global_i in enumerate(valid_idx):
        chem_peers = chem_ind[local_i, 1:]
        umap_peers = umap_ind_final[local_i, 1:]
        broad_candidates = umap_ind_broad[local_i, 1:]

        chem_distances = np.linalg.norm(Xv[local_i] - Xv[chem_peers], axis=1)
        umap_chem_distances = np.linalg.norm(Xv[local_i] - Xv[umap_peers], axis=1)

        candidate_distances = np.linalg.norm(Xv[local_i] - Xv[broad_candidates], axis=1)
        hybrid_peers = broad_candidates[np.argsort(candidate_distances)[:k_chem]]
        hybrid_distances = np.linalg.norm(Xv[local_i] - Xv[hybrid_peers], axis=1)

        chem_knn_mean_distance[global_i] = float(np.mean(chem_distances))
        umap_knn_mean_chem_distance[global_i] = float(np.mean(umap_chem_distances))
        hybrid_peer_mean_chem_distance[global_i] = float(np.mean(hybrid_distances))
        peer_overlap_chem_umap[global_i] = len(set(chem_peers) & set(umap_peers)) / k_chem

    return df.with_columns(
        pl.Series("chem_knn_mean_distance", chem_knn_mean_distance),
        pl.Series("umap_knn_mean_chem_distance", umap_knn_mean_chem_distance),
        pl.Series("hybrid_peer_mean_chem_distance", hybrid_peer_mean_chem_distance),
        pl.Series("peer_overlap_chem_umap", peer_overlap_chem_umap),
    )


def add_hybrid_peer_analysis(df: pl.DataFrame, config: dict) -> pl.DataFrame:
    """
    Add hybrid UMAP-shortlisted / 12D-refined peer metrics.

    Academic rationale
    ------------------
    UMAP coordinates are useful for preserving local neighbourhood topology,
    but 2D Euclidean distances in UMAP space are not chemically meaningful.
    This method therefore uses UMAP only as a fast shortlist generator:

    1. Find nearby candidate peers in 2D UMAP space.
    2. Re-rank those candidates by true Euclidean distance in the original
       multivariate z-score chemistry space.
    3. Compare the official WFD typology of the focal site with the typology
       mix of its final chemical peers.

    The expensive numeric part is vectorized: after sklearn produces the
    shortlist matrix, NumPy broadcasts the focal row against all shortlisted
    candidate rows and computes every 12D distance in one operation.
    """
    peer_config = config.get("peer_analysis", {})
    shortlist_k = int(peer_config.get("umap_shortlist_k", 50))
    final_k = int(peer_config.get("final_peer_k", 5))
    cross_threshold = float(peer_config.get("cross_type_threshold", 0.4))
    strong_threshold = float(peer_config.get("strong_agreement_threshold", 0.8))

    n_sites = df.height
    peer_agreement_ratio = np.full(n_sites, np.nan, dtype=float)
    dominant_peer_type = np.array([None] * n_sites, dtype=object)
    is_cross_type = np.zeros(n_sites, dtype=bool)
    is_strong_agreement = np.zeros(n_sites, dtype=bool)
    peer_site_ids: list[list[str]] = [[] for _ in range(n_sites)]

    required_umap_cols = {"umap_x", "umap_y"}
    if not required_umap_cols.issubset(df.columns):
        log.warning("Hybrid peer analysis skipped: missing umap_x/umap_y")
        return df.with_columns(
            pl.Series("peer_agreement_ratio", peer_agreement_ratio),
            pl.Series("dominant_peer_type", dominant_peer_type.tolist()),
            pl.Series("is_cross_type", is_cross_type),
            pl.Series("is_strong_agreement", is_strong_agreement),
            pl.Series("peer_site_ids", peer_site_ids, dtype=pl.List(pl.Utf8)),
        )

    z_cols = get_z_score_cols(df)
    if not z_cols:
        log.warning("Hybrid peer analysis skipped: no numeric *_z columns found")
        return df.with_columns(
            pl.Series("peer_agreement_ratio", peer_agreement_ratio),
            pl.Series("dominant_peer_type", dominant_peer_type.tolist()),
            pl.Series("is_cross_type", is_cross_type),
            pl.Series("is_strong_agreement", is_strong_agreement),
            pl.Series("peer_site_ids", peer_site_ids, dtype=pl.List(pl.Utf8)),
        )

    from sklearn.neighbors import NearestNeighbors

    umap_coords = df.select(["umap_x", "umap_y"]).to_numpy().astype(float)
    valid_umap = np.isfinite(umap_coords).all(axis=1)

    if valid_umap.sum() < 2:
        log.warning("Hybrid peer analysis skipped: fewer than two sites have valid UMAP coordinates")
        return df.with_columns(
            pl.Series("peer_agreement_ratio", peer_agreement_ratio),
            pl.Series("dominant_peer_type", dominant_peer_type.tolist()),
            pl.Series("is_cross_type", is_cross_type),
            pl.Series("is_strong_agreement", is_strong_agreement),
            pl.Series("peer_site_ids", peer_site_ids, dtype=pl.List(pl.Utf8)),
        )

    # Z-score distance space. A missing z-score is imputed as 0: chemically,
    # this is the neutral "matches expected peer baseline" value, and it keeps
    # partial feature coverage from breaking the peer calculation.
    z_space = df.select(z_cols).to_numpy().astype(float)
    z_space = np.nan_to_num(z_space, nan=0.0, posinf=0.0, neginf=0.0)

    valid_idx = np.where(valid_umap)[0]
    U = umap_coords[valid_umap]
    Z = z_space[valid_umap]

    k_short_eff = min(shortlist_k, valid_idx.size - 1)
    k_final_eff = min(final_k, k_short_eff)
    if k_final_eff < 1:
        log.warning("Hybrid peer analysis skipped: final_peer_k resolves to zero")
        return df.with_columns(
            pl.Series("peer_agreement_ratio", peer_agreement_ratio),
            pl.Series("dominant_peer_type", dominant_peer_type.tolist()),
            pl.Series("is_cross_type", is_cross_type),
            pl.Series("is_strong_agreement", is_strong_agreement),
            pl.Series("peer_site_ids", peer_site_ids, dtype=pl.List(pl.Utf8)),
        )

    # Step A: UMAP shortlist. The first neighbour is the focal site itself, so
    # it is discarded before 12D refinement.
    umap_nn = NearestNeighbors(n_neighbors=k_short_eff + 1, metric="euclidean")
    umap_nn.fit(U)
    _, shortlist_local = umap_nn.kneighbors(U)
    candidate_local = shortlist_local[:, 1:]

    # Step B: true 12D refinement. This is a single vectorized distance block:
    # shape = (n_valid_sites, shortlist_k, n_z_features).
    candidate_distances = np.linalg.norm(Z[:, None, :] - Z[candidate_local], axis=2)
    final_order = np.argsort(candidate_distances, axis=1)[:, :k_final_eff]
    final_peer_local = np.take_along_axis(candidate_local, final_order, axis=1)
    final_peer_global = valid_idx[final_peer_local]

    if "wfd_type" in df.columns:
        wfd_types = np.array([_clean_typology(value) for value in df["wfd_type"].to_list()], dtype=object)
    else:
        wfd_types = np.array(["Unknown"] * n_sites, dtype=object)
    site_ids = np.array([str(value) for value in df["site_id"].to_list()], dtype=object)

    if "wfd_type" in df.columns:
        focal_has_official_type = np.array([_valid_label(value) for value in df["wfd_type"].to_list()], dtype=bool)
    else:
        focal_has_official_type = np.zeros(n_sites, dtype=bool)

    focal_types = wfd_types[valid_idx]
    peer_types = wfd_types[final_peer_global]

    # Step C: dominant peer typology. Peer arrays are already sorted by true
    # 12D distance, so when type counts tie, the first tied type encountered is
    # the one represented by the closest chemical peer.
    for local_i, global_i in enumerate(valid_idx):
        labels = peer_types[local_i].tolist()
        counts = {label: labels.count(label) for label in set(labels)}
        max_count = max(counts.values())
        dominant = next(label for label in labels if counts[label] == max_count)
        dominant_ratio = max_count / k_final_eff
        same_official_ratio = float((peer_types[local_i] == focal_types[local_i]).mean())
        has_official_type = bool(focal_has_official_type[global_i])

        dominant_peer_type[global_i] = None if dominant == "Unknown" else dominant
        peer_agreement_ratio[global_i] = same_official_ratio if has_official_type else dominant_ratio
        is_cross_type[global_i] = has_official_type and same_official_ratio <= cross_threshold
        is_strong_agreement[global_i] = has_official_type and same_official_ratio >= strong_threshold
        peer_site_ids[global_i] = site_ids[final_peer_global[local_i]].tolist()

    log.info(
        "Hybrid peer analysis: %s z-score columns, shortlist_k=%s, final_peer_k=%s, "
        "cross_type=%s, strong_agreement=%s",
        len(z_cols),
        k_short_eff,
        k_final_eff,
        int(is_cross_type.sum()),
        int(is_strong_agreement.sum()),
    )

    return df.with_columns(
        pl.Series("peer_agreement_ratio", peer_agreement_ratio),
        pl.Series("dominant_peer_type", dominant_peer_type.tolist()),
        pl.Series("is_cross_type", is_cross_type),
        pl.Series("is_strong_agreement", is_strong_agreement),
        pl.Series("peer_site_ids", peer_site_ids, dtype=pl.List(pl.Utf8)),
    )


def add_resolved_wfd_type(df: pl.DataFrame) -> pl.DataFrame:
    """
    Infer a WFD type for unclassified sites when chemical peers agree.

    If dominant_peer_type is null, for example because the nearest peers are
    also unclassified, wfd_type_resolved intentionally remains null.
    """
    return df.with_columns(
        pl.when(
            pl.col("wfd_type").is_null()
            & (pl.col("peer_agreement_ratio") >= 0.6)
            & pl.col("dominant_peer_type").is_not_null()
        )
        .then(pl.col("dominant_peer_type"))
        .otherwise(pl.col("wfd_type"))
        .alias("wfd_type_resolved")
    ).with_columns(
        pl.when(pl.col("wfd_type").is_null() & pl.col("wfd_type_resolved").is_not_null())
        .then(pl.lit(True))
        .otherwise(pl.lit(False))
        .alias("wfd_type_inferred")
    )


def add_z_scores_and_rank(
    df: pl.DataFrame,
    feature_cols: list[str],
    z_scores: np.ndarray,
    score_name: str = "anomaly_score",
) -> pl.DataFrame:
    anomaly_scores = _rms_z(z_scores)

    z_series = [pl.Series(f"{col}_z", z_scores[:, i]) for i, col in enumerate(feature_cols)]
    df = df.with_columns(z_series)
    df = df.with_columns(pl.Series(score_name, anomaly_scores))
    df = df.with_columns(
        pl.col(score_name).rank(descending=True).cast(pl.Int32).alias("anomaly_rank")
    )
    return df


def flag_anomalies(df: pl.DataFrame, config: dict) -> pl.DataFrame:
    """Flag sites above the configured anomaly-score percentile."""
    pct = config["anomaly"]["flag_percentile"]
    scores = df["anomaly_score"].drop_nulls().to_numpy()
    if scores.size == 0:
        threshold = np.nan
    else:
        threshold = float(np.percentile(scores, pct))

    df = df.with_columns(
        (pl.col("anomaly_score") >= threshold).alias("is_flagged"),
        pl.lit(threshold).alias("flag_threshold"),
    )

    n_flagged = df.filter(pl.col("is_flagged")).height
    log.info(f"Flagged {n_flagged} sites above {pct}th percentile (threshold={threshold:.3f})")
    return df


def identify_drivers(
    df: pl.DataFrame,
    feature_cols: list[str],
    threshold_std: float = 2.0,
) -> pl.DataFrame:
    """
    Identify determinands with |peer z-score| above threshold.
    Also stores the strongest driver and its signed z-score.
    """
    z_cols = [f"{c}_z" for c in feature_cols if f"{c}_z" in df.columns]
    if not z_cols:
        return df.with_columns(
            pl.lit("").alias("anomaly_drivers"),
            pl.lit(None).cast(pl.Utf8).alias("top_anomaly_driver"),
            pl.lit(None).cast(pl.Float64).alias("top_anomaly_driver_z"),
        )

    Z = df.select(z_cols).to_numpy().astype(float)
    drivers = []
    top_driver = []
    top_driver_z = []

    for row in Z:
        finite = np.isfinite(row)
        if not finite.any():
            drivers.append("")
            top_driver.append(None)
            top_driver_z.append(np.nan)
            continue

        order = np.argsort(np.abs(row))[::-1]
        top_idx = next((idx for idx in order if np.isfinite(row[idx])), None)
        top_driver.append(feature_cols[top_idx] if top_idx is not None else None)
        top_driver_z.append(float(row[top_idx]) if top_idx is not None else np.nan)

        row_drivers = [
            feature_cols[idx]
            for idx in order
            if np.isfinite(row[idx]) and abs(row[idx]) >= threshold_std
        ]
        drivers.append("|".join(row_drivers))

    return df.with_columns(
        pl.Series("anomaly_drivers", drivers),
        pl.Series("top_anomaly_driver", top_driver),
        pl.Series("top_anomaly_driver_z", top_driver_z),
    )


def run():
    """Execute the scoring layer."""
    config = load_config()

    proc_dir = get_path(config, "processed_data")
    input_path = proc_dir / "site_fingerprints.parquet"

    log.info("=" * 60)
    log.info("LAYER 3 - SCORE")
    log.info("=" * 60)

    df = pl.read_parquet(input_path)
    log.info(f"Loaded {df.height:,} site fingerprints")

    feature_cols = get_feature_cols(df, config, proc_dir)
    if not feature_cols:
        raise ValueError("No chemistry feature columns found in site_fingerprints.parquet")
    log.info(f"Scoring on {len(feature_cols)} features: {feature_cols}")

    method = config["anomaly"]["method"]
    min_group_size = config["anomaly"].get("min_observations", 10)
    log.info(f"Scoring method: {method}")

    if method == "typology_peers":
        df, z_scores = score_by_typology_peers(df, feature_cols, min_group_size=min_group_size)
        df = add_z_scores_and_rank(df, feature_cols, z_scores)
        k = config["anomaly"]["geographic_k"]
        df = score_by_geographic_neighbours(df, feature_cols, k=k)
    elif method == "geographic_neighbours":
        k = config["anomaly"]["geographic_k"]
        _, z_scores = score_by_typology_peers(df, feature_cols, min_group_size=min_group_size)
        df = add_z_scores_and_rank(df, feature_cols, z_scores)
        df = score_by_geographic_neighbours(df, feature_cols, k=k)
        df = df.with_columns(pl.col("geo_anomaly_score").alias("anomaly_score"))
        df = df.with_columns(
            pl.col("anomaly_score").rank(descending=True).cast(pl.Int32).alias("anomaly_rank")
        )
    else:
        log.warning(f"Unknown method '{method}', defaulting to typology_peers")
        df, z_scores = score_by_typology_peers(df, feature_cols, min_group_size=min_group_size)
        df = add_z_scores_and_rank(df, feature_cols, z_scores)

    df = add_embedding_peer_diagnostics(df, feature_cols)
    df = add_hybrid_peer_analysis(df, config)
    df = add_resolved_wfd_type(df)
    df = flag_anomalies(df, config)

    notable_std = config["narrate"]["notable_std_threshold"]
    df = identify_drivers(df, feature_cols, threshold_std=notable_std)

    out_path = proc_dir / "scored_sites.parquet"
    df.write_parquet(out_path)
    log.info(f"Saved -> {out_path} ({df.height:,} sites)")

    preview_cols = [
        c
        for c in [
            "site_id",
            "site_label",
            "anomaly_score",
            "anomaly_rank",
            "score_reference",
            "anomaly_drivers",
        ]
        if c in df.columns
    ]
    log.info("Top 10 most anomalous sites:")
    _safe_print(df.sort("anomaly_rank").head(10).select(preview_cols))


if __name__ == "__main__":
    run()
