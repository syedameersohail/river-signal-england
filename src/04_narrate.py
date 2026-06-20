"""
Layer 4 - NARRATE
=================
Generate plain-English summaries for flagged sites and produce the final ranked
anomaly feed consumed by the frontend.

Input:  data/processed/scored_sites.parquet
Output: data/output/ranked_feed.json
        data/output/site_summaries.json
"""

import json
import math
from datetime import date, datetime

import polars as pl

from utils import load_config, get_path, setup_logger, ensure_dir


log = setup_logger("04_narrate")


# These names match the updated common_core_panel in config/settings.yaml.
DETERMINAND_CONTEXT = {
    "Temperature of Water": {
        "label": "water temperature",
        "high": "elevated water temperature, which can reduce oxygen availability and stress temperature-sensitive aquatic life",
        "low": "unusually low water temperature for its peer group",
        "unit": "deg C",
    },
    "pH": {
        "label": "pH",
        "high": "elevated pH, meaning the water is more alkaline than expected and may reflect algal activity, geology, or alkaline inputs",
        "low": "low pH, meaning the water is more acidic than expected and may indicate acidification or acidic inputs",
        "unit": "pH units",
    },
    "Alkalinity to pH 4.5 as CaCO3": {
        "label": "alkalinity",
        "high": "high alkalinity, indicating strongly buffered water often associated with chalk or limestone catchments",
        "low": "low alkalinity, meaning the river has limited buffering capacity against acid inputs",
        "unit": "mg/L as CaCO3",
    },
    "Conductivity at 25 C": {
        "label": "conductivity",
        "high": "high conductivity, suggesting elevated dissolved ions from geology, sewage effluent, road runoff, agriculture, or industrial inputs",
        "low": "unusually low conductivity, typical of softer, less mineralised waters",
        "unit": "uS/cm",
    },
    "Oxygen, Dissolved as O2": {
        "label": "dissolved oxygen",
        "high": "unusually high dissolved oxygen, which can occur during strong photosynthesis or algal activity",
        "low": "low dissolved oxygen, which can stress aquatic life and may indicate organic pollution or sewage inputs",
        "unit": "mg/L",
    },
    "Nitrite as N": {
        "label": "nitrite",
        "high": "elevated nitrite, a reactive nitrogen form that can be associated with sewage, organic pollution, or incomplete nitrification",
        "low": "very low nitrite relative to comparable sites",
        "unit": "mg/L as N",
    },
    "Nitrate as N": {
        "label": "nitrate",
        "high": "elevated nitrate, commonly linked to agricultural fertiliser runoff, land drainage, or sewage treatment inputs",
        "low": "very low nitrate, often seen in less enriched or upland catchments",
        "unit": "mg/L as N",
    },
    "Ammoniacal Nitrogen as N": {
        "label": "ammonia-related nitrogen",
        "high": "elevated ammonia-related nitrogen, which can be associated with sewage, slurry, landfill drainage, manure, or other organic waste",
        "low": "very low ammoniacal nitrogen, consistent with limited recent organic pollution pressure",
        "unit": "mg/L as N",
    },
    "Orthophosphate, reactive as P": {
        "label": "reactive orthophosphate",
        "high": "elevated reactive phosphate, a key eutrophication pressure often linked to sewage effluent, agriculture, or urban runoff",
        "low": "very low reactive phosphate, suggesting limited phosphorus enrichment",
        "unit": "mg/L as P",
    },
    "Nitrogen, Total Oxidised as N": {
        "label": "oxidised nitrogen",
        "high": "elevated total oxidised nitrogen, indicating nitrate/nitrite enrichment often associated with diffuse agricultural or wastewater sources",
        "low": "low total oxidised nitrogen compared with peer sites",
        "unit": "mg/L as N",
    },
    "Ammonia un-ionised as N": {
        "label": "toxic ammonia",
        "high": "elevated toxic ammonia, the ammonia form most harmful to fish and river insects",
        "low": "very low un-ionised ammonia relative to comparable sites",
        "unit": "mg/L as N",
    },
    "Oxygen, Dissolved, % Saturation": {
        "label": "dissolved oxygen saturation",
        "high": "high oxygen saturation, which can indicate intense photosynthesis or algal activity",
        "low": "low oxygen saturation, which can indicate oxygen stress from organic pollution, slow flow, or high biological demand",
        "unit": "% saturation",
    },
}


def _code_to_name(config: dict) -> dict[str, str]:
    return {str(code): name for code, name in config["common_core_panel"].items()}


def _normalise_driver(driver: str, config: dict) -> str:
    code_lookup = _code_to_name(config)
    return code_lookup.get(str(driver), driver)


def _driver_z(row: dict, driver: str, config: dict):
    name = _normalise_driver(driver, config)
    for candidate in (f"{name}_z", f"{driver}_z"):
        if candidate in row:
            return row.get(candidate)
    return None


def _format_driver(driver: str, z_val: float | None, config: dict) -> dict:
    name = _normalise_driver(driver, config)
    context = DETERMINAND_CONTEXT.get(name, {"label": name})

    if z_val is None:
        direction = "unknown"
        phrase = f"unusual {context.get('label', name)}"
    else:
        direction = "high" if z_val > 0 else "low"
        phrase = context.get(direction, f"{direction} {context.get('label', name)}")

    return {
        "name": name,
        "label": context.get("label", name),
        "z": None if z_val is None else round(float(z_val), 3),
        "direction": direction,
        "description": phrase,
        "unit": context.get("unit", ""),
    }


def _site_name(row: dict) -> str:
    return row.get("site_label") or row.get("site_name") or row.get("site_id") or "Unknown site"


def clean_site_name(name: str) -> str:
    """Title case but preserve common abbreviations."""
    cleaned = str(name).title()
    for word in ["Of", "The", "At", "On", "In", "To", "And"]:
        cleaned = cleaned.replace(f" {word} ", f" {word.lower()} ")
    return cleaned


def _display_name(row: dict) -> str:
    return clean_site_name(_site_name(row))


def _site_meta_value(row: dict, key: str):
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _iso_date(row: dict, key: str) -> str | None:
    value = _site_meta_value(row, key)
    if value is None:
        return None
    if hasattr(value, "date") and callable(value.date):
        return value.date().isoformat()
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    return str(value)


def _date_value(row: dict, key: str) -> date | None:
    value = _site_meta_value(row, key)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _last_sample_year(row: dict) -> int | None:
    value = _date_value(row, "last_sample")
    return value.year if value else None


def _avg_days_between_visits(row: dict) -> float | None:
    value = _site_meta_value(row, "avg_days_between_visits")
    if value is None:
        return None
    return round(float(value), 1)


def get_confidence_tier(visits, last_sample_year, config: dict) -> str:
    confidence_config = config.get("data_confidence", {})
    well_config = confidence_config.get("well_monitored", {})
    moderate_config = confidence_config.get("moderate", {})

    well_visits = int(well_config.get("min_visits", 30))
    well_year = int(well_config.get("min_last_sample_year", 2023))
    moderate_visits = int(moderate_config.get("min_visits", 12))
    moderate_year = int(moderate_config.get("min_last_sample_year", 2020))

    visits = int(visits or 0)
    last_sample_year = int(last_sample_year or 0)

    visit_tier = (
        "well" if visits >= well_visits
        else "moderate" if visits >= moderate_visits
        else "limited"
    )
    recency_tier = (
        "well" if last_sample_year >= well_year
        else "moderate" if last_sample_year >= moderate_year
        else "limited"
    )
    tiers = {"limited": 0, "moderate": 1, "well": 2}
    return min(visit_tier, recency_tier, key=lambda tier: tiers[tier])


def _resolved_wfd_type(row: dict) -> str | None:
    return row.get("wfd_type_resolved") or row.get("wfd_type")


def _reference_sentence(row: dict) -> str:
    reference = row.get("score_reference")
    if reference and reference != "global":
        return f" Compared with similar {reference} rivers, this profile looks unusual."

    wfd_type = _resolved_wfd_type(row)
    if wfd_type:
        return f" The site is in WFD type {wfd_type}, though scoring used a broader fallback reference."

    return " The comparison uses the national chemistry reference because no usable WFD peer group was available."


def _peer_typology_sentence(row: dict) -> str:
    """Explain whether chemical peers agree with official WFD typology."""
    focal_wfd_type = _resolved_wfd_type(row) or "Unknown"
    dominant_peer_type = row.get("dominant_peer_type") or focal_wfd_type
    peer_label = dominant_peer_type if dominant_peer_type != "Unknown" else "other monitored"

    if not row.get("wfd_type") and dominant_peer_type != "Unknown":
        return (
            f" This site has no official WFD classification, but its chemistry is consistent "
            f"with {dominant_peer_type} rivers based on peer analysis."
        )

    if row.get("wfd_type") and bool(row.get("is_cross_type", False)):
        return (
            f" Its chemistry looks out of character for a {focal_wfd_type} river"
            f" and is closer to {peer_label} rivers in the peer analysis."
            " This suggests possible external pollution pressure and should be investigated further."
        )

    if bool(row.get("is_strong_agreement", False)):
        return (
            f" Its chemical signature strongly aligns with its official "
            f"{focal_wfd_type} classification."
        )

    return ""


def _peer_fields(row: dict) -> dict:
    """Fields from Layer 3 hybrid KNN analysis, exported for every site."""
    ratio = row.get("peer_agreement_ratio")
    if ratio is None:
        ratio_out = None
    else:
        ratio_float = float(ratio)
        ratio_out = None if math.isnan(ratio_float) else round(ratio_float, 4)

    peer_site_ids = row.get("peer_site_ids") or []

    return {
        "peer_agreement_ratio": ratio_out,
        "dominant_peer_type": row.get("dominant_peer_type") or "Unknown",
        "is_cross_type": bool(row.get("is_cross_type", False)),
        "is_strong_agreement": bool(row.get("is_strong_agreement", False)),
        "peer_site_ids": list(peer_site_ids),
        "wfd_type_resolved": row.get("wfd_type_resolved"),
        "wfd_type_inferred": bool(row.get("wfd_type_inferred", False)),
    }


def _normal_summary(row: dict) -> str:
    return "Chemistry is consistent with similar rivers. No unusual patterns detected."


def _driver_names(driver_details: list[dict]) -> list[str]:
    return [str(driver.get("name", "")).lower() for driver in driver_details]


def _has_high_driver(driver_details: list[dict], *needles: str) -> bool:
    lowered_needles = tuple(needle.lower() for needle in needles)
    return any(
        driver.get("direction") == "high"
        and any(needle in str(driver.get("name", "")).lower() for needle in lowered_needles)
        for driver in driver_details
    )


def _has_low_driver(driver_details: list[dict], *needles: str) -> bool:
    lowered_needles = tuple(needle.lower() for needle in needles)
    return any(
        driver.get("direction") == "low"
        and any(needle in str(driver.get("name", "")).lower() for needle in lowered_needles)
        for driver in driver_details
    )


def _public_flagged_summary(driver_details: list[dict]) -> str:
    """Return the short public opening shown before technical details."""
    names = _driver_names(driver_details)

    if any("ammonia" in name or "ammoniacal" in name for name in names):
        return (
            "High ammonia pollution signals stand out here.\n\n"
            "This river has unusually high ammonia-related readings compared with similar rivers. "
            "These can harm fish, insects, and other river life.\n\n"
            "The pattern may point to sewage, slurry, landfill drainage, or other organic pollution, "
            "so it should be investigated further."
        )

    if _has_low_driver(driver_details, "oxygen"):
        return (
            "Low oxygen signals stand out here.\n\n"
            "This river has unusually low oxygen readings compared with similar rivers. "
            "Low oxygen can harm fish, insects, and other river life.\n\n"
            "The pattern may indicate organic pollution pressure, slow flow, warm water, "
            "or other stress, so it should be investigated further."
        )

    if _has_high_driver(driver_details, "phosphate", "nitrate", "nitrite", "nitrogen"):
        return (
            "High nutrient pollution signals stand out here.\n\n"
            "This river has unusually high nutrient-related readings compared with similar rivers. "
            "These can feed algal growth and put pressure on river life.\n\n"
            "The pattern may indicate sewage, farm runoff, or other nutrient pollution, "
            "so it should be investigated further."
        )

    if _has_high_driver(driver_details, "conductivity"):
        return (
            "High dissolved minerals stand out here.\n\n"
            "This river has unusually high conductivity compared with similar rivers. "
            "That means the water contains more dissolved salts and minerals than expected.\n\n"
            "The pattern can be associated with geology, road runoff, wastewater, industry, "
            "or other external inputs, so it should be investigated further."
        )

    if any("ph" in name for name in names):
        return (
            "Unusual acidity or alkalinity stands out here.\n\n"
            "This river has pH readings that look unusual compared with similar rivers. "
            "Large pH differences can stress fish, insects, and other river life.\n\n"
            "The pattern may reflect natural geology or external inputs, so it should be "
            "investigated further."
        )

    if _has_high_driver(driver_details, "temperature"):
        return (
            "High water temperature stands out here.\n\n"
            "This river is warmer than expected compared with similar rivers. Warm water can "
            "reduce oxygen availability and stress river wildlife.\n\n"
            "The pattern may reflect weather, low flows, or external pressure, so it should be "
            "investigated further."
        )

    return (
        "Unusual chemistry stands out here.\n\n"
        "This river has readings that differ from similar rivers. That does not prove the cause, "
        "but it shows the site looks out of character.\n\n"
        "The pattern should be investigated further."
    )


def _driver_sentence(driver_details: list[dict]) -> str:
    descriptions = [str(driver["description"]).rstrip(".") for driver in driver_details]
    if not descriptions:
        return "No single chemical measure dominates the result."
    if len(descriptions) == 1:
        return f"The main signal is {descriptions[0]}."
    return f"The main signals are {'; '.join(descriptions)}."


def _remaining_drivers_sentence(driver_details: list[dict]) -> str:
    if len(driver_details) <= 1:
        return "No other single chemical measure dominates the result."
    return _driver_sentence(driver_details[1:])


def _flagged_summary(row: dict, driver_details: list[dict]) -> str:
    site_label = _display_name(row)
    rank = int(row["anomaly_rank"])
    peer_count = row.get("score_peer_group_size") or 0
    peer_count_text = f"{int(peer_count):,}" if peer_count else "other"
    wfd_type = _resolved_wfd_type(row) or row.get("score_reference") or "comparable"
    water_body_name = row.get("water_body_name")
    region = row.get("region") or "this region"

    drivers_sentence = _driver_sentence(driver_details)
    top_driver_plain = driver_details[0]["label"] if driver_details else "unusual chemistry"

    template_index = rank % 4
    if template_index == 1:
        return f"{site_label} ranks #{rank} nationally. {drivers_sentence}"
    if template_index == 2:
        return (
            f"Elevated {top_driver_plain} stands out at {site_label}, which ranks #{rank} "
            f"nationally for unusual chemistry. {_remaining_drivers_sentence(driver_details)}"
        )
    if template_index == 3:
        return (
            f"Among {peer_count_text} similar {wfd_type} rivers, {site_label} is one of the "
            f"most chemically unusual (ranked #{rank} nationally). {drivers_sentence}"
        )
    location = f"On the {water_body_name} in {region}" if water_body_name else f"In {region}"
    return (
        f"{location}, {site_label} shows chemistry that stands out from comparable rivers. "
        f"{drivers_sentence} It ranks #{rank} nationally."
    )


def narrate_site(row: dict, feature_cols: list[str], config: dict) -> dict:
    """Generate a plain-English summary for a single site."""
    drivers_str = row.get("anomaly_drivers") or ""
    raw_drivers = [d.strip() for d in drivers_str.split("|") if d.strip()]

    if not raw_drivers and row.get("top_anomaly_driver"):
        raw_drivers = [row["top_anomaly_driver"]]

    driver_details = [
        _format_driver(driver, _driver_z(row, driver, config), config)
        for driver in raw_drivers
    ]

    site_name = _site_name(row)
    rank = int(row["anomaly_rank"])
    score = float(row["anomaly_score"])
    visits = _site_meta_value(row, "distinct_sample_dates")
    confidence_tier = get_confidence_tier(visits, _last_sample_year(row), config)

    if not bool(row.get("is_flagged", False)):
        summary = _normal_summary(row)
        driver_details = []
    elif not driver_details:
        summary = (
            "Unusual chemistry stands out here.\n\n"
            "This river looks different from similar rivers, but no single chemical measure "
            "dominates the result.\n\n"
            "The pattern should be investigated further."
        )
    else:
        summary = _flagged_summary(row, driver_details)

    return {
        "site_id": row["site_id"],
        "site_label": site_name,
        "display_name": _display_name(row),
        "lat": row.get("lat"),
        "lon": row.get("lon"),
        "region": row.get("region"),
        "area": row.get("area"),
        "sub_area": row.get("sub_area"),
        "anomaly_rank": rank,
        "anomaly_score": round(score, 4),
        "is_flagged": bool(row.get("is_flagged", False)),
        "flag_threshold": row.get("flag_threshold"),
        "score_reference": row.get("score_reference"),
        "score_peer_group_size": row.get("score_peer_group_size"),
        "total_observations": _site_meta_value(row, "total_observations"),
        "first_sample": _iso_date(row, "first_sample"),
        "last_sample": _iso_date(row, "last_sample"),
        "distinct_sample_dates": _site_meta_value(row, "distinct_sample_dates"),
        "avg_days_between_visits": _avg_days_between_visits(row),
        "confidence_tier": confidence_tier,
        "drivers": driver_details,
        "summary": summary,
        "wfd_type": row.get("wfd_type"),
        "wfd_type_resolved": row.get("wfd_type_resolved"),
        "wfd_type_inferred": bool(row.get("wfd_type_inferred", False)),
        "water_body_id": row.get("water_body_id"),
        "water_body_name": row.get("water_body_name"),
        **_peer_fields(row),
    }


def minimal_site(row: dict) -> dict:
    config = load_config()
    visits = _site_meta_value(row, "distinct_sample_dates")
    return {
        "site_id": row["site_id"],
        "site_label": _site_name(row),
        "display_name": _display_name(row),
        "lat": row.get("lat"),
        "lon": row.get("lon"),
        "anomaly_rank": int(row["anomaly_rank"]),
        "anomaly_score": round(float(row["anomaly_score"]), 4),
        "is_flagged": bool(row.get("is_flagged", False)),
        "top_anomaly_driver": row.get("top_anomaly_driver"),
        "top_anomaly_driver_z": row.get("top_anomaly_driver_z"),
        "summary": _normal_summary(row),
        "total_observations": _site_meta_value(row, "total_observations"),
        "first_sample": _iso_date(row, "first_sample"),
        "last_sample": _iso_date(row, "last_sample"),
        "distinct_sample_dates": _site_meta_value(row, "distinct_sample_dates"),
        "avg_days_between_visits": _avg_days_between_visits(row),
        "confidence_tier": get_confidence_tier(visits, _last_sample_year(row), config),
        "wfd_type": row.get("wfd_type"),
        "wfd_type_resolved": row.get("wfd_type_resolved"),
        "wfd_type_inferred": bool(row.get("wfd_type_inferred", False)),
        **_peer_fields(row),
    }


def build_feed(df: pl.DataFrame, config: dict, feature_cols: list[str]) -> list[dict]:
    """Build ranked feed with a plain-English narrative for every site."""
    df = df.sort("anomaly_rank")

    feed = []
    for row in df.to_dicts():
        feed.append(narrate_site(row, feature_cols, config))

    return feed


def data_period(proc_dir) -> tuple[str | None, str | None]:
    observations_path = proc_dir / "cleaned_observations.parquet"
    if not observations_path.exists():
        return None, None

    period = pl.scan_parquet(observations_path).select(
        pl.col("sample_dt").min().alias("start"),
        pl.col("sample_dt").max().alias("end"),
    ).collect().to_dicts()[0]

    start = period.get("start")
    end = period.get("end")
    return (
        start.date().isoformat() if start else None,
        end.date().isoformat() if end else None,
    )


def get_feature_cols(df: pl.DataFrame, config: dict) -> list[str]:
    panel_names = [name for name in config["common_core_panel"].values() if name in df.columns]
    if panel_names:
        return panel_names

    z_cols = [c[:-2] for c in df.columns if c.endswith("_z")]
    return [c for c in z_cols if c in df.columns]


def run():
    """Execute the narration layer."""
    config = load_config()

    proc_dir = get_path(config, "processed_data")
    out_dir = ensure_dir(get_path(config, "output"))
    input_path = proc_dir / "scored_sites.parquet"

    log.info("=" * 60)
    log.info("LAYER 4 - NARRATE")
    log.info("=" * 60)

    df = pl.read_parquet(input_path)
    log.info(f"Loaded {df.height:,} scored sites")

    feature_cols = get_feature_cols(df, config)
    feed = build_feed(df, config, feature_cols)
    data_period_start, data_period_end = data_period(proc_dir)

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_period_start": data_period_start,
        "data_period_end": data_period_end,
        "total_sites": len(feed),
        "flagged_sites": sum(1 for entry in feed if entry.get("is_flagged")),
        "top_n_with_narratives": len(feed),
        "scoring_method": config["anomaly"]["method"],
        "feature_cols": feature_cols,
        "panel": config["common_core_panel"],
        "feed": feed,
    }

    feed_path = out_dir / "ranked_feed.json"
    with open(feed_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"Saved ranked feed -> {feed_path}")

    flagged = [entry for entry in feed if entry.get("is_flagged") and entry.get("summary")]
    summaries_path = out_dir / "site_summaries.json"
    with open(summaries_path, "w") as f:
        json.dump(flagged, f, indent=2, default=str)
    log.info(f"Saved {len(flagged)} flagged site summaries -> {summaries_path}")

    log.info("Top 5 anomalous sites:")
    for entry in feed[:5]:
        if "summary" in entry:
            log.info(f"  #{entry['anomaly_rank']}: {entry['summary'][:120]}...")


if __name__ == "__main__":
    run()
