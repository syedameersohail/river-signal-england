"""Merge site incident summary data into ranked_feed.json."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INCIDENT_PATH = ROOT / "data" / "processed" / "site_incident_summary.json"
FEED_PATH = ROOT / "data" / "output" / "ranked_feed.json"
FRONTEND_FEED_PATH = ROOT / "frontend" / "public" / "data" / "ranked_feed.json"

INCIDENT_KEYS = [
    "total_pollution_incidents",
    "most_recent_pollution_date",
    "primary_pollution_cause",
    "total_edm_spills",
    "total_spill_hours",
    "most_recent_spill_date",
    "has_any_incidents",
    "total_all_incidents",
]


def load_incident_lookup(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    return {r["site_id"]: r for r in records}


def sanitise_incident(record: dict) -> dict:
    out = {}
    for key in INCIDENT_KEYS:
        val = record.get(key)
        if key == "total_spill_hours":
            out[key] = float(val) if val is not None else 0.0
        elif key == "has_any_incidents":
            out[key] = bool(val)
        elif key in ("most_recent_pollution_date", "most_recent_spill_date"):
            if val is None:
                out[key] = None
            else:
                out[key] = str(val)
        else:
            out[key] = val
    return out


def main():
    incident_lookup = load_incident_lookup(INCIDENT_PATH)
    print(f"Loaded {len(incident_lookup)} site incident records.")

    with open(FEED_PATH, "r", encoding="utf-8") as f:
        feed_data = json.load(f)

    sites = feed_data["feed"]
    sites_with = 0
    sites_without = 0

    for site in sites:
        sid = site.get("site_id")
        inc = incident_lookup.get(sid)

        if inc and inc.get("has_any_incidents"):
            site["incidents"] = sanitise_incident(inc)
            sites_with += 1
        else:
            site.pop("incidents", None)
            sites_without += 1

    feed_data["feed"] = sites

    for dest in (FEED_PATH, FRONTEND_FEED_PATH):
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(feed_data, f, indent=2, ensure_ascii=False)
        print(f"Saved: {dest}")

    total = sites_with + sites_without
    print(
        f"Merged incident data into {total} sites. "
        f"{sites_with} sites had incidents, "
        f"{sites_without} sites had no incidents and were left unchanged."
    )


if __name__ == "__main__":
    main()
